"""
AI Auto-Patcher — automatically applies code fixes to production source files.

Workflow:
  1. Parse the stack trace to find the most likely culprit file(s).
  2. Read the current contents of each candidate file.
  3. Ask Claude to produce a unified diff that fixes the error.
  4. Create a timestamped backup of the file before touching it.
  5. Apply the diff with Python's `difflib` (no external `patch` binary needed).
  6. Return a PatchResult describing what happened.

Safety guarantees:
  - Only patches files inside the project SOURCE ROOT (never .env, secrets, migrations).
  - Backup is written alongside the original: <file>.bak.<timestamp>
  - Any failure (bad diff, file-not-found, permission error) is caught and returned
    as PatchResult(success=False, error=...) — never raises.
  - Dry-run mode available for testing without writing to disk.
"""

import difflib
import json
import os
import re
import shutil
import structlog
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = structlog.get_logger()

# ── Configuration ──────────────────────────────────────────────────────────────

# Absolute path to the project root (where src/ lives)
_PROJECT_ROOT = Path(__file__).resolve().parents[3]  # …/rcm-ai-platform

# Only patch files under src/ — never touch .env, alembic, migrations, or tests
_PATCHABLE_PREFIXES = ("src/",)

# Never patch these regardless of path
_BLOCKED_PATTERNS = (
    ".env",
    "secrets",
    "alembic",
    "/migrations/",
    "__pycache__",
    ".pyc",
    "node_modules",
)

# Max source file size we'll read (bytes) to keep prompt cost low
_MAX_FILE_BYTES = 60_000


# ── Result dataclass ───────────────────────────────────────────────────────────

@dataclass
class PatchResult:
    success: bool
    file_patched: Optional[str] = None      # relative path inside project root
    backup_path: Optional[str] = None       # absolute path to .bak file
    diff_applied: Optional[str] = None      # the unified diff text
    error: Optional[str] = None             # human-readable failure reason
    confidence: str = "low"                 # mirrors analyzer confidence
    dry_run: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


# ── Public entry point ─────────────────────────────────────────────────────────

def auto_patch(
    error_type: str,
    message: str,
    stack_trace: str,
    suggested_fix: str,
    root_cause: str,
    confidence: str = "medium",
    dry_run: bool = False,
) -> PatchResult:
    """
    Main entry point.  Called from the Celery task after AI analysis completes.
    Returns a PatchResult — never raises.
    """
    try:
        return _do_patch(
            error_type=error_type,
            message=message,
            stack_trace=stack_trace,
            suggested_fix=suggested_fix,
            root_cause=root_cause,
            confidence=confidence,
            dry_run=dry_run,
        )
    except Exception as exc:
        logger.error("auto_patch_unexpected_failure", error=str(exc))
        return PatchResult(success=False, error=f"Unexpected patcher error: {str(exc)[:300]}")


# ── Internal helpers ──────────────────────────────────────────────────────────

def _do_patch(
    error_type: str,
    message: str,
    stack_trace: str,
    suggested_fix: str,
    root_cause: str,
    confidence: str,
    dry_run: bool,
) -> PatchResult:
    # Step 1 — find candidate source file from stack trace
    candidate = _find_patchable_file(stack_trace)
    if not candidate:
        return PatchResult(
            success=False,
            error="No patchable source file found in stack trace (all frames outside src/).",
        )

    abs_path = _PROJECT_ROOT / candidate
    if not abs_path.exists():
        return PatchResult(
            success=False,
            file_patched=str(candidate),
            error=f"Source file not found on disk: {abs_path}",
        )

    # Step 2 — read current file contents
    try:
        original_source = abs_path.read_text(encoding="utf-8")
    except Exception as exc:
        return PatchResult(
            success=False,
            file_patched=str(candidate),
            error=f"Could not read source file: {exc}",
        )

    if len(original_source.encode()) > _MAX_FILE_BYTES:
        # Truncate for prompt but still patch the full file
        source_for_prompt = original_source[:_MAX_FILE_BYTES] + "\n# … (truncated for analysis)"
    else:
        source_for_prompt = original_source

    # Step 3 — ask Claude for a unified diff
    diff_text = _generate_diff_via_claude(
        file_path=str(candidate),
        source=source_for_prompt,
        error_type=error_type,
        message=message,
        stack_trace=stack_trace[:3000],
        root_cause=root_cause,
        suggested_fix=suggested_fix,
    )
    if not diff_text:
        return PatchResult(
            success=False,
            file_patched=str(candidate),
            error="Claude returned an empty or unparseable diff.",
        )

    # Step 4 — validate diff looks sane (basic sanity check)
    if not _diff_applies_cleanly(original_source, diff_text):
        return PatchResult(
            success=False,
            file_patched=str(candidate),
            diff_applied=diff_text,
            error="Generated diff does not apply cleanly to the current source — skipping to avoid corruption.",
        )

    if dry_run:
        return PatchResult(
            success=True,
            file_patched=str(candidate),
            diff_applied=diff_text,
            confidence=confidence,
            dry_run=True,
        )

    # Step 5 — create backup
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = abs_path.with_suffix(abs_path.suffix + f".bak.{ts}")
    try:
        shutil.copy2(abs_path, backup_path)
    except Exception as exc:
        return PatchResult(
            success=False,
            file_patched=str(candidate),
            diff_applied=diff_text,
            error=f"Failed to create backup before patching: {exc}",
        )

    # Step 6 — apply the diff
    patched_source = _apply_unified_diff(original_source, diff_text)
    if patched_source is None:
        # Remove the backup we just created
        try:
            backup_path.unlink()
        except Exception:
            pass
        return PatchResult(
            success=False,
            file_patched=str(candidate),
            backup_path=str(backup_path),
            diff_applied=diff_text,
            error="Patch application failed — diff did not apply to file. Backup removed.",
        )

    # Step 7 — write patched file
    try:
        abs_path.write_text(patched_source, encoding="utf-8")
    except Exception as exc:
        return PatchResult(
            success=False,
            file_patched=str(candidate),
            backup_path=str(backup_path),
            diff_applied=diff_text,
            error=f"Failed to write patched file: {exc}",
        )

    logger.info(
        "auto_patch_applied",
        file=str(candidate),
        backup=str(backup_path),
        diff_lines=len(diff_text.splitlines()),
    )

    return PatchResult(
        success=True,
        file_patched=str(candidate),
        backup_path=str(backup_path),
        diff_applied=diff_text,
        confidence=confidence,
        dry_run=False,
    )


def _find_patchable_file(stack_trace: str) -> Optional[Path]:
    """
    Parse a Python stack trace and return the last frame that points to a
    patchable file inside src/.  Returns a Path relative to _PROJECT_ROOT.

    Python tracebacks look like:
      File "/app/src/core/error_intelligence/tasks.py", line 44, in record_and_analyze_error
    """
    # Match quoted file paths in Python tracebacks
    pattern = re.compile(r'File ["\']([^"\']+\.py)["\']')
    candidates = pattern.findall(stack_trace)

    for raw_path in reversed(candidates):
        p = Path(raw_path)

        # Try to make it relative to _PROJECT_ROOT
        try:
            rel = p.relative_to(_PROJECT_ROOT)
        except ValueError:
            # The path may be /app/src/... inside Docker — strip /app prefix
            path_str = raw_path.lstrip("/")
            # Remove leading 'app/' if present (Docker container path)
            if path_str.startswith("app/"):
                path_str = path_str[4:]
            rel = Path(path_str)

        rel_str = str(rel).replace("\\", "/")

        # Must be under src/
        if not any(rel_str.startswith(prefix) for prefix in _PATCHABLE_PREFIXES):
            continue

        # Must not be blocked
        if any(blocked in rel_str for blocked in _BLOCKED_PATTERNS):
            continue

        # Verify the file exists
        if (_PROJECT_ROOT / rel).exists():
            return rel

    return None


def _generate_diff_via_claude(
    file_path: str,
    source: str,
    error_type: str,
    message: str,
    stack_trace: str,
    root_cause: str,
    suggested_fix: str,
) -> Optional[str]:
    """
    Ask Claude claude-sonnet-4-6 to generate a unified diff that fixes the error.
    Returns the raw diff string, or None on failure.
    """
    try:
        from src.config import get_settings
        settings = get_settings()

        if not settings.anthropic_api_key:
            logger.warning("auto_patch_skip", reason="no_api_key")
            return None

        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        prompt = f"""You are a senior Python engineer working on Aethera AI, a HIPAA-compliant healthcare RCM platform.
A production error has been automatically detected and analyzed. Your job is to produce an exact unified diff
that fixes the root cause in the source file shown below.

ERROR:
  Type: {error_type}
  Message: {message}

ROOT CAUSE (from AI analysis):
{root_cause}

SUGGESTED FIX (from AI analysis):
{suggested_fix}

STACK TRACE (truncated):
```
{stack_trace}
```

SOURCE FILE: {file_path}
```python
{source}
```

INSTRUCTIONS:
1. Produce ONLY a valid unified diff (standard `diff -u` format) that fixes the error.
2. Do NOT produce markdown — output only the raw diff text, starting with `---`.
3. Keep the fix minimal — change the fewest lines necessary to fix the root cause.
4. Do NOT alter unrelated logic, formatting, or comments.
5. The diff MUST apply cleanly to the source shown above.
6. If the fix cannot be expressed as a safe, minimal patch (e.g. the root cause requires
   architectural changes, a migration, or changes to multiple files), output EXACTLY:
   CANNOT_PATCH: <one sentence reason>

Produce the unified diff now:"""

        response = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()

        # Detect the "cannot patch" signal
        if raw.upper().startswith("CANNOT_PATCH"):
            logger.info("auto_patch_cannot_patch", reason=raw[:200])
            return None

        # Strip markdown fences if Claude wrapped in ```diff ... ```
        if raw.startswith("```"):
            lines = raw.splitlines()
            # Remove opening ``` line and closing ``` line
            inner = []
            in_block = False
            for line in lines:
                if line.startswith("```") and not in_block:
                    in_block = True
                    continue
                if line.startswith("```") and in_block:
                    break
                if in_block:
                    inner.append(line)
            raw = "\n".join(inner)

        # Must look like a unified diff
        if not raw.startswith("---"):
            logger.warning("auto_patch_bad_diff_format", preview=raw[:100])
            return None

        return raw

    except Exception as exc:
        logger.error("auto_patch_claude_error", error=str(exc))
        return None


def _diff_applies_cleanly(original: str, diff_text: str) -> bool:
    """
    Quick sanity check: verify that every `-` line in the diff actually appears
    in the original source (as a substring check, not full patch simulation).
    Returns True if the diff looks plausible.
    """
    try:
        orig_lines = set(line.rstrip() for line in original.splitlines())
        for line in diff_text.splitlines():
            if line.startswith("--- ") or line.startswith("+++ ") or line.startswith("@@"):
                continue
            if line.startswith("-") and not line.startswith("---"):
                removed_line = line[1:].rstrip()
                if removed_line and removed_line not in orig_lines:
                    logger.debug("auto_patch_line_not_found", line=removed_line[:80])
                    return False
        return True
    except Exception:
        return False


def _apply_unified_diff(original: str, diff_text: str) -> Optional[str]:
    """
    Apply a unified diff to the original source using Python stdlib difflib.
    Returns the patched string, or None if the patch fails.
    """
    try:
        original_lines = original.splitlines(keepends=True)

        # Parse hunk headers to extract line number information
        patched_lines = list(original_lines)  # start with a copy

        # Use a simple hunk-by-hunk application
        diff_lines = diff_text.splitlines()

        hunks = []
        current_hunk = None

        for line in diff_lines:
            if line.startswith("--- ") or line.startswith("+++ "):
                continue
            if line.startswith("@@"):
                if current_hunk is not None:
                    hunks.append(current_hunk)
                # Parse @@ -a,b +c,d @@ format
                m = re.match(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', line)
                if m:
                    orig_start = int(m.group(1))
                    current_hunk = {
                        "orig_start": orig_start,
                        "lines": [],
                    }
            elif current_hunk is not None:
                current_hunk["lines"].append(line)

        if current_hunk is not None:
            hunks.append(current_hunk)

        if not hunks:
            return None

        # Apply hunks in reverse order to preserve line numbers
        result = list(original_lines)

        for hunk in reversed(hunks):
            orig_start = hunk["orig_start"] - 1  # 0-indexed
            hunk_lines = hunk["lines"]

            # Build the expected original block and replacement block
            orig_block = []
            new_block = []

            for h_line in hunk_lines:
                if h_line.startswith("-"):
                    orig_block.append(h_line[1:])
                elif h_line.startswith("+"):
                    new_block.append(h_line[1:])
                else:
                    # Context line — appears in both
                    orig_block.append(h_line[1:] if h_line.startswith(" ") else h_line)
                    new_block.append(h_line[1:] if h_line.startswith(" ") else h_line)

            # Add newlines if missing
            orig_block = [l if l.endswith("\n") else l + "\n" for l in orig_block]
            new_block = [l if l.endswith("\n") else l + "\n" for l in new_block]

            end = orig_start + len(orig_block)

            # Verify the block matches
            current_block = result[orig_start:end]
            current_stripped = [l.rstrip() for l in current_block]
            expected_stripped = [l.rstrip() for l in orig_block]

            if current_stripped != expected_stripped:
                logger.warning(
                    "auto_patch_hunk_mismatch",
                    orig_start=orig_start + 1,
                    expected=expected_stripped[:3],
                    got=current_stripped[:3],
                )
                return None

            result[orig_start:end] = new_block

        return "".join(result)

    except Exception as exc:
        logger.error("auto_patch_apply_failed", error=str(exc))
        return None
