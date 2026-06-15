"""
Rules Engine — Claim scrubbing with NCCI edits, MUE, modifier validation,
and payer-specific rules. Combines deterministic rules with AI risk analysis.
"""

import structlog
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from src.core.eligibility.plan_rules import evaluate_plan_type_rules

logger = structlog.get_logger()


class RuleSeverity(str, Enum):
    ERROR = "error"      # Claim cannot be submitted
    WARNING = "warning"  # Should be reviewed, may cause denial
    INFO = "info"        # Informational, may improve clean claim rate


class RuleType(str, Enum):
    NCCI_EDIT = "ncci_edit"
    MUE = "mue"
    MODIFIER = "modifier"
    POS_TOS = "pos_tos"
    ELIGIBILITY = "eligibility"
    AUTHORIZATION = "authorization"
    TIMELY_FILING = "timely_filing"
    DUPLICATE = "duplicate"
    AGE_GENDER = "age_gender"
    PAYER_SPECIFIC = "payer_specific"
    MEDICAL_NECESSITY = "medical_necessity"


@dataclass
class ScrubFinding:
    rule_type: RuleType
    severity: RuleSeverity
    message: str
    suggestion: str | None = None
    auto_fixable: bool = False
    claim_line_number: int | None = None
    rule_reference: str | None = None


@dataclass
class ScrubResult:
    claim_id: str
    score: int = 100  # 0-100, starts at 100
    findings: list[ScrubFinding] = field(default_factory=list)
    denial_risk_score: float = 0.0

    @property
    def errors(self) -> list[ScrubFinding]:
        return [f for f in self.findings if f.severity == RuleSeverity.ERROR]

    @property
    def warnings(self) -> list[ScrubFinding]:
        return [f for f in self.findings if f.severity == RuleSeverity.WARNING]

    @property
    def ready_to_submit(self) -> bool:
        return len(self.errors) == 0


class ClaimScrubber:
    """
    Multi-pass claim scrubbing engine.
    Runs all applicable rules and returns a comprehensive scrub result.
    """

    def __init__(self, ncci_data: dict | None = None, mue_data: dict | None = None):
        """
        Args:
            ncci_data: NCCI Column 1/Column 2 edit pairs loaded from CMS data
            mue_data: Medically Unlikely Edits loaded from CMS data
        """
        self.ncci_edits = ncci_data or {}
        self.mue_limits = mue_data or {}

    def scrub(self, claim: dict, payer_rules: list[dict] | None = None) -> ScrubResult:
        """
        Run all scrubbing rules against a claim.

        Args:
            claim: Claim data dict with keys: claim_lines, diagnoses, payer, etc.
            payer_rules: Payer-specific rules from the Payer Intelligence module
        """
        result = ScrubResult(claim_id=claim.get("claim_id", "unknown"))

        # Pass 1: NCCI Column 1/Column 2 Edits (code bundling)
        result.findings.extend(self._check_ncci_edits(claim))

        # Pass 2: Medically Unlikely Edits (unit limits)
        result.findings.extend(self._check_mue(claim))

        # Pass 3: Modifier Validation
        result.findings.extend(self._check_modifiers(claim))

        # Pass 4: Place of Service / Type of Service consistency
        result.findings.extend(self._check_pos_consistency(claim))

        # Pass 5: Plan-type business rules (referral / out-of-network / delegated billing)
        result.findings.extend(self._check_plan_type_rules(claim))

        # Pass 5: Diagnosis pointer validation
        result.findings.extend(self._check_diagnosis_pointers(claim))

        # Pass 6: Duplicate claim detection
        result.findings.extend(self._check_duplicates(claim))

        # Pass 7: Timely filing check
        result.findings.extend(self._check_timely_filing(claim))

        # Pass 8: Age/Gender appropriateness
        result.findings.extend(self._check_age_gender(claim))

        # Pass 9: Payer-specific rules
        if payer_rules:
            result.findings.extend(self._check_payer_rules(claim, payer_rules))

        # Calculate scrub score
        result.score = self._calculate_score(result.findings)

        logger.info(
            "claim_scrubbed",
            claim_id=result.claim_id,
            score=result.score,
            errors=len(result.errors),
            warnings=len(result.warnings),
        )

        return result

    def _check_ncci_edits(self, claim: dict) -> list[ScrubFinding]:
        """
        Check NCCI Column 1/Column 2 procedure-to-procedure edits.
        Column 1 codes are comprehensive; Column 2 codes are component.
        When both appear on same claim, Column 2 is bundled into Column 1
        unless a valid modifier exception applies.
        """
        findings = []
        lines = claim.get("claim_lines", [])

        for i, line1 in enumerate(lines):
            for j, line2 in enumerate(lines):
                if i >= j:
                    continue

                code1 = line1.get("cpt_code", "")
                code2 = line2.get("cpt_code", "")

                # Check if this pair is an NCCI edit
                edit = self.ncci_edits.get(f"{code1}:{code2}") or self.ncci_edits.get(f"{code2}:{code1}")
                if edit:
                    # Check modifier exception
                    modifier_exception = edit.get("modifier_indicator", "0")
                    has_modifier_59 = any(
                        m in ["59", "XE", "XP", "XS", "XU"]
                        for m in line2.get("modifiers", []) + line1.get("modifiers", [])
                    )

                    if modifier_exception == "1" and has_modifier_59:
                        findings.append(ScrubFinding(
                            rule_type=RuleType.NCCI_EDIT,
                            severity=RuleSeverity.INFO,
                            message=f"NCCI edit {code1}/{code2}: modifier exception applied",
                            claim_line_number=j + 1,
                        ))
                    else:
                        column1 = edit.get("column1", code1)
                        column2 = edit.get("column2", code2)
                        findings.append(ScrubFinding(
                            rule_type=RuleType.NCCI_EDIT,
                            severity=RuleSeverity.ERROR,
                            message=f"NCCI bundling: {column2} is bundled into {column1}. Cannot bill separately without modifier exception.",
                            suggestion=f"Add modifier 59/XE/XP/XS/XU to {column2} if services were distinct, or remove {column2}.",
                            auto_fixable=False,
                            claim_line_number=j + 1,
                            rule_reference=f"NCCI PTP Edit {column1}/{column2}",
                        ))

        return findings

    def _check_mue(self, claim: dict) -> list[ScrubFinding]:
        """Check Medically Unlikely Edits (unit limits per CPT code)."""
        findings = []
        for i, line in enumerate(claim.get("claim_lines", [])):
            code = line.get("cpt_code", "")
            units = line.get("units", 1)
            mue = self.mue_limits.get(code)

            if mue and units > mue.get("max_units", 999):
                findings.append(ScrubFinding(
                    rule_type=RuleType.MUE,
                    severity=RuleSeverity.ERROR,
                    message=f"MUE violation: {code} has max {mue['max_units']} units, claim has {units}",
                    suggestion=f"Reduce units to {mue['max_units']} or split across dates of service if clinically appropriate",
                    claim_line_number=i + 1,
                    rule_reference=f"MUE {code}: {mue['max_units']} units ({mue.get('rationale', 'CMS')})",
                ))

        return findings

    def _check_modifiers(self, claim: dict) -> list[ScrubFinding]:
        """Validate modifier usage and combinations."""
        findings = []
        for i, line in enumerate(claim.get("claim_lines", [])):
            modifiers = line.get("modifiers", [])

            # Check for invalid modifier combinations
            if "26" in modifiers and "TC" in modifiers:
                findings.append(ScrubFinding(
                    rule_type=RuleType.MODIFIER,
                    severity=RuleSeverity.ERROR,
                    message="Cannot use both modifier 26 (professional) and TC (technical) on same line",
                    suggestion="Remove one modifier — they are mutually exclusive",
                    auto_fixable=False,
                    claim_line_number=i + 1,
                ))

            # Check E/M with modifier 25
            code = line.get("cpt_code", "")
            if code.startswith("99") and len(code) == 5:  # E/M code
                has_procedures = any(
                    not l.get("cpt_code", "").startswith("99")
                    for l in claim.get("claim_lines", [])
                )
                if has_procedures and "25" not in modifiers:
                    findings.append(ScrubFinding(
                        rule_type=RuleType.MODIFIER,
                        severity=RuleSeverity.WARNING,
                        message=f"E/M code {code} billed with procedures — consider modifier 25 for significant, separately identifiable service",
                        suggestion="Add modifier 25 if the E/M was significant and separately identifiable",
                        auto_fixable=True,
                        claim_line_number=i + 1,
                    ))

        return findings

    def _check_plan_type_rules(self, claim: dict) -> list[ScrubFinding]:
        """Plan-type business rules (referral, out-of-network, delegated billing).
        Reads optional plan context from the claim dict; no-ops if plan_type is absent."""
        plan_type = claim.get("plan_type")
        if not plan_type:
            cov = claim.get("coverage")
            if isinstance(cov, dict):
                plan_type = cov.get("plan_type")
        if not plan_type:
            return []
        pos = claim.get("place_of_service")
        for ln in (claim.get("claim_lines") or []):
            if isinstance(ln, dict) and ln.get("place_of_service"):
                pos = str(ln["place_of_service"])
                break
        raw = evaluate_plan_type_rules(
            plan_type=plan_type,
            network_status=claim.get("network_status"),
            referral_on_file=claim.get("referral_on_file"),
            is_specialist=claim.get("is_specialist"),
            place_of_service=pos,
            is_emergency=claim.get("is_emergency"),
        )
        sev = {"error": RuleSeverity.ERROR, "warning": RuleSeverity.WARNING, "info": RuleSeverity.INFO}
        rtype = {"PLAN_REFERRAL_REQUIRED": RuleType.AUTHORIZATION}
        return [
            ScrubFinding(
                rule_type=rtype.get(f.code, RuleType.ELIGIBILITY),
                severity=sev.get(f.severity, RuleSeverity.INFO),
                message=f.message,
                suggestion=f.suggestion,
                rule_reference="HealthCare.gov plan-type rules",
            )
            for f in raw
        ]
    def _check_pos_consistency(self, claim: dict) -> list[ScrubFinding]:
        """
        Check Place of Service consistency with procedure codes.

        Rules:
        - POS 11 (office): should not have facility-only CPTs (99231-99233, 99238, 99239)
        - POS 21/22/23 (hospital): should not have office-only CPTs (99202-99215)
        - POS 12 (home): CPTs should be home visit codes (99341-99350)
        """
        findings = []
        pos = claim.get("place_of_service", "")

        # Facility-only inpatient subsequent care / discharge codes
        facility_only_cpts = set()
        for c in range(99231, 99234):  # 99231-99233
            facility_only_cpts.add(str(c))
        facility_only_cpts.update({"99238", "99239"})

        # Office-only outpatient E/M codes (new and established patient)
        office_only_cpts = set()
        for c in range(99202, 99216):  # 99202-99215
            office_only_cpts.add(str(c))

        # Home visit codes
        home_visit_cpts = set()
        for c in range(99341, 99351):  # 99341-99350
            home_visit_cpts.add(str(c))

        for i, line in enumerate(claim.get("claim_lines", [])):
            code = line.get("cpt_code", "")
            line_pos = line.get("place_of_service", pos)

            # POS 11 (Office) with facility-only codes
            if line_pos == "11" and code in facility_only_cpts:
                findings.append(ScrubFinding(
                    rule_type=RuleType.POS_TOS,
                    severity=RuleSeverity.WARNING,
                    message=f"Line {i+1}: CPT {code} is a facility-only code but POS is 11 (Office)",
                    suggestion=f"Verify POS is correct. Inpatient codes {code} are typically billed with hospital POS (21/22/23).",
                    claim_line_number=i + 1,
                    rule_reference="CMS POS Guidelines",
                ))

            # POS 21/22/23 (Hospital inpatient/outpatient/ER) with office-only codes
            elif line_pos in {"21", "22", "23"} and code in office_only_cpts:
                pos_labels = {"21": "Inpatient Hospital", "22": "On-Campus Outpatient", "23": "Emergency Room"}
                pos_label = pos_labels.get(line_pos, f"Hospital POS {line_pos}")
                findings.append(ScrubFinding(
                    rule_type=RuleType.POS_TOS,
                    severity=RuleSeverity.WARNING,
                    message=f"Line {i+1}: CPT {code} is an office-only E/M code but POS is {line_pos} ({pos_label})",
                    suggestion=f"Verify POS is correct. Office E/M codes {code} should be billed with POS 11.",
                    claim_line_number=i + 1,
                    rule_reference="CMS POS Guidelines",
                ))

            # POS 12 (Home) with non-home-visit codes
            elif line_pos == "12" and code and code not in home_visit_cpts:
                # Only flag if it's an E/M code (starts with 99) to avoid false positives on procedures
                if code.startswith("99") and len(code) == 5:
                    findings.append(ScrubFinding(
                        rule_type=RuleType.POS_TOS,
                        severity=RuleSeverity.WARNING,
                        message=f"Line {i+1}: CPT {code} used with POS 12 (Home) — expected home visit codes (99341-99350)",
                        suggestion="Use home visit CPT codes (99341-99350) for home POS, or verify POS is correct.",
                        claim_line_number=i + 1,
                        rule_reference="CMS POS Guidelines",
                    ))

        return findings

    def _check_diagnosis_pointers(self, claim: dict) -> list[ScrubFinding]:
        """Validate diagnosis code pointers on each line."""
        findings = []
        claim_dx = set(claim.get("diagnoses", []))

        for i, line in enumerate(claim.get("claim_lines", [])):
            pointers = line.get("icd_pointers", [])
            if not pointers:
                findings.append(ScrubFinding(
                    rule_type=RuleType.MEDICAL_NECESSITY,
                    severity=RuleSeverity.ERROR,
                    message=f"Line {i+1}: No diagnosis pointer — at least one ICD-10 code required",
                    claim_line_number=i + 1,
                ))
            else:
                for dx in pointers:
                    if dx not in claim_dx:
                        findings.append(ScrubFinding(
                            rule_type=RuleType.MEDICAL_NECESSITY,
                            severity=RuleSeverity.ERROR,
                            message=f"Line {i+1}: Diagnosis pointer {dx} not found in claim diagnoses",
                            claim_line_number=i + 1,
                        ))

        return findings

    def _check_duplicates(self, claim: dict) -> list[ScrubFinding]:
        """
        Check for potential duplicate claim submissions.

        Inter-claim duplicate detection requires DB access (not available here).
        This pass checks for intra-claim duplicates: two lines on the same claim
        with the same CPT code, flagging as potential duplicate billing.
        """
        findings = []
        lines = claim.get("claim_lines", [])

        # Build a map of (cpt_code, service_date) → list of line indices
        seen: dict[tuple, list[int]] = {}
        for i, line in enumerate(lines):
            code = line.get("cpt_code", "")
            service_date = line.get("service_date", claim.get("service_date", ""))
            key = (code, str(service_date))
            if key not in seen:
                seen[key] = []
            seen[key].append(i)

        for (code, service_date), line_indices in seen.items():
            if len(line_indices) > 1 and code:
                line_nums = [str(idx + 1) for idx in line_indices]
                findings.append(ScrubFinding(
                    rule_type=RuleType.DUPLICATE,
                    severity=RuleSeverity.ERROR,
                    message=(
                        f"Intra-claim duplicate: CPT {code} appears on lines {', '.join(line_nums)}"
                        + (f" for service date {service_date}" if service_date else "")
                    ),
                    suggestion=(
                        f"Remove duplicate line(s) for CPT {code}, or add appropriate modifiers "
                        "(e.g., 59, 76, 77) if the service was genuinely performed multiple times."
                    ),
                    auto_fixable=False,
                    claim_line_number=line_indices[0] + 1,
                    rule_reference="CMS Duplicate Claim Policy",
                ))

        return findings

    def _check_timely_filing(self, claim: dict) -> list[ScrubFinding]:
        """Check if claim is within payer's timely filing limit."""
        findings = []
        from datetime import date, timedelta

        service_date = claim.get("service_date")
        filing_limit_days = claim.get("payer_timely_filing_days", 365)

        if service_date and isinstance(service_date, date):
            deadline = service_date + timedelta(days=filing_limit_days)
            days_remaining = (deadline - date.today()).days

            if days_remaining < 0:
                findings.append(ScrubFinding(
                    rule_type=RuleType.TIMELY_FILING,
                    severity=RuleSeverity.ERROR,
                    message=f"Timely filing deadline exceeded by {abs(days_remaining)} days",
                ))
            elif days_remaining < 30:
                findings.append(ScrubFinding(
                    rule_type=RuleType.TIMELY_FILING,
                    severity=RuleSeverity.WARNING,
                    message=f"Timely filing deadline in {days_remaining} days — submit urgently",
                ))

        return findings

    def _check_age_gender(self, claim: dict) -> list[ScrubFinding]:
        """
        Check CPT code appropriateness for patient age and gender.

        Rules:
        - Pediatric codes (99381-99385): patient age must be < 18
        - OB/GYN codes (59400, 59410, 59430, 58150, 58260, 58550): female gender required
        - PSA screening (86316, G0103): male gender required
        - Neonatal codes (99460-99465): patient age must be < 1
        """
        findings = []
        age = claim.get("patient_age")
        gender = claim.get("patient_gender", "").upper().strip()

        # Define rule sets as (cpt_set, condition_fn, message_template)
        pediatric_codes = {str(c) for c in range(99381, 99386)}  # 99381-99385
        obgyn_codes = {"59400", "59410", "59430", "58150", "58260", "58550"}
        psa_codes = {"86316", "G0103"}
        neonatal_codes = {str(c) for c in range(99460, 99466)}  # 99460-99465

        for i, line in enumerate(claim.get("claim_lines", [])):
            code = line.get("cpt_code", "")
            if not code:
                continue

            # Pediatric preventive codes: require age < 18
            if code in pediatric_codes:
                if age is not None and age >= 18:
                    findings.append(ScrubFinding(
                        rule_type=RuleType.AGE_GENDER,
                        severity=RuleSeverity.ERROR,
                        message=(
                            f"Line {i+1}: CPT {code} is a pediatric preventive code "
                            f"but patient age is {age} (must be < 18)"
                        ),
                        suggestion="Use adult preventive CPT codes (99386-99387) for patients age 18+.",
                        claim_line_number=i + 1,
                        rule_reference="CPT Preventive Medicine Guidelines",
                    ))

            # OB/GYN codes: require female gender
            elif code in obgyn_codes:
                if gender and gender not in ("F", "FEMALE"):
                    findings.append(ScrubFinding(
                        rule_type=RuleType.AGE_GENDER,
                        severity=RuleSeverity.ERROR,
                        message=(
                            f"Line {i+1}: CPT {code} is an OB/GYN procedure code "
                            f"but patient gender is recorded as '{gender}'"
                        ),
                        suggestion="Verify patient gender. OB/GYN codes require female patient.",
                        claim_line_number=i + 1,
                        rule_reference="CPT OB/GYN Section Guidelines",
                    ))

            # PSA screening codes: require male gender
            elif code in psa_codes:
                if gender and gender not in ("M", "MALE"):
                    findings.append(ScrubFinding(
                        rule_type=RuleType.AGE_GENDER,
                        severity=RuleSeverity.ERROR,
                        message=(
                            f"Line {i+1}: CPT {code} is a PSA screening code "
                            f"but patient gender is recorded as '{gender}'"
                        ),
                        suggestion="Verify patient gender. PSA screening requires male patient.",
                        claim_line_number=i + 1,
                        rule_reference="CMS PSA Screening Policy",
                    ))

            # Neonatal codes: require age < 1 (infant)
            elif code in neonatal_codes:
                if age is not None and age >= 1:
                    findings.append(ScrubFinding(
                        rule_type=RuleType.AGE_GENDER,
                        severity=RuleSeverity.ERROR,
                        message=(
                            f"Line {i+1}: CPT {code} is a neonatal care code "
                            f"but patient age is {age} (must be < 1 year)"
                        ),
                        suggestion="Neonatal codes (99460-99465) are only appropriate for patients under 1 year old.",
                        claim_line_number=i + 1,
                        rule_reference="CPT Neonatal Intensive Care Guidelines",
                    ))

        return findings

    def _check_payer_rules(self, claim: dict, payer_rules: list[dict]) -> list[ScrubFinding]:
        """
        Apply payer-specific billing rules.

        Built-in rules by payer type:
        - Medicare: require referring provider NPI for specialist claims
        - Medicaid: flag lines > $10,000 for manual review
        - Commercial: flag surgery CPTs (10000-69999) without prior auth number
        """
        findings = []
        payer_name = (claim.get("payer_name") or claim.get("payer", "")).upper()
        lines = claim.get("claim_lines", [])

        # ── Medicare rules ──────────────────────────────────────────────
        if "MEDICARE" in payer_name:
            referring_npi = claim.get("referring_provider_npi", "").strip()
            rendering_npi = claim.get("rendering_provider_npi", "").strip()
            specialty_code = claim.get("rendering_provider_specialty", "").strip()

            # PCP specialty codes (family practice, general practice, internal medicine, etc.)
            pcp_specialty_codes = {"01", "08", "11", "38", "84"}

            # Flag missing referring NPI for non-PCP specialists
            if (
                specialty_code
                and specialty_code not in pcp_specialty_codes
                and not referring_npi
            ):
                findings.append(ScrubFinding(
                    rule_type=RuleType.PAYER_SPECIFIC,
                    severity=RuleSeverity.WARNING,
                    message=(
                        f"Medicare: Referring provider NPI is missing for specialist claim "
                        f"(specialty {specialty_code})"
                    ),
                    suggestion="Add referring provider NPI (Box 17b on CMS-1500). Required for Medicare specialist claims.",
                    rule_reference="Medicare Claims Processing Manual Ch. 26",
                ))

        # ── Medicaid rules ──────────────────────────────────────────────
        if "MEDICAID" in payer_name:
            for i, line in enumerate(lines):
                charge = line.get("charge_amount", 0) or 0
                try:
                    charge = float(charge)
                except (TypeError, ValueError):
                    charge = 0.0

                if charge > 10000.0:
                    findings.append(ScrubFinding(
                        rule_type=RuleType.PAYER_SPECIFIC,
                        severity=RuleSeverity.WARNING,
                        message=(
                            f"Line {i+1}: Medicaid claim line charge ${charge:,.2f} exceeds $10,000 — "
                            f"flagged for manual review"
                        ),
                        suggestion="Verify charge amount is correct. High-dollar Medicaid claims may require additional documentation.",
                        claim_line_number=i + 1,
                        rule_reference="Medicaid High-Dollar Claim Review Policy",
                    ))

        # ── Commercial insurance rules ──────────────────────────────────
        is_commercial = (
            payer_name
            and "MEDICARE" not in payer_name
            and "MEDICAID" not in payer_name
        )
        if is_commercial:
            prior_auth = (claim.get("prior_auth_number") or "").strip()
            for i, line in enumerate(lines):
                code = line.get("cpt_code", "")
                # Surgery range: 10000-69999
                try:
                    code_int = int(code)
                    is_surgery = 10000 <= code_int <= 69999
                except (ValueError, TypeError):
                    is_surgery = False

                if is_surgery and not prior_auth:
                    findings.append(ScrubFinding(
                        rule_type=RuleType.PAYER_SPECIFIC,
                        severity=RuleSeverity.WARNING,
                        message=(
                            f"Line {i+1}: Surgical CPT {code} submitted without prior authorization number"
                        ),
                        suggestion=(
                            "Obtain and enter prior authorization number before submitting. "
                            "Commercial payers typically require prior auth for surgical procedures."
                        ),
                        auto_fixable=False,
                        claim_line_number=i + 1,
                        rule_reference="Commercial Payer Prior Authorization Requirements",
                    ))

        # ── Dynamic payer rules from payer intelligence module ──────────
        for rule in payer_rules:
            rule_type = rule.get("rule_type", "")
            definition = rule.get("rule_definition", {})
            # Dynamic rule evaluation placeholder — extend as payer intelligence grows
            # rule_type examples: "frequency_limit", "pre_cert_required", "modifier_required"

        return findings

    def _calculate_score(self, findings: list[ScrubFinding]) -> int:
        """Calculate claim cleanliness score (0-100)."""
        score = 100
        for finding in findings:
            if finding.severity == RuleSeverity.ERROR:
                score -= 25
            elif finding.severity == RuleSeverity.WARNING:
                score -= 10
            elif finding.severity == RuleSeverity.INFO:
                score -= 2
        return max(0, score)
