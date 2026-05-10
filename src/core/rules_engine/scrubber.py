"""
Rules Engine — Claim scrubbing with NCCI edits, MUE, modifier validation,
and payer-specific rules. Combines deterministic rules with AI risk analysis.
"""

import structlog
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

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

    def _check_pos_consistency(self, claim: dict) -> list[ScrubFinding]:
        """Check Place of Service consistency with procedure codes."""
        findings = []
        pos = claim.get("place_of_service", "")

        for i, line in enumerate(claim.get("claim_lines", [])):
            code = line.get("cpt_code", "")
            line_pos = line.get("place_of_service", pos)

            # Facility vs non-facility checks
            facility_pos = {"21", "22", "23", "24", "26", "31", "34", "41", "42", "51", "52", "53", "56", "61"}
            if line_pos in facility_pos:
                # Certain codes should not be billed with facility POS by professionals
                pass  # TODO: Implement facility/non-facility rate logic

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
        """Check for potential duplicate claim submissions."""
        # TODO: Query database for existing claims with same patient, DOS, codes, payer
        return []

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
        """Check code appropriateness for patient age and gender."""
        findings = []
        age = claim.get("patient_age")
        gender = claim.get("patient_gender", "").upper()

        for i, line in enumerate(claim.get("claim_lines", [])):
            code = line.get("cpt_code", "")
            # TODO: Cross-reference CPT codes with age/gender appropriateness table
            # e.g., OB codes for male patients, pediatric codes for adults

        return findings

    def _check_payer_rules(self, claim: dict, payer_rules: list[dict]) -> list[ScrubFinding]:
        """Apply payer-specific billing rules."""
        findings = []

        for rule in payer_rules:
            rule_type = rule.get("rule_type", "")
            definition = rule.get("rule_definition", {})

            # TODO: Implement payer-specific rule evaluation
            # Examples:
            # - Auth required for specific CPT codes
            # - Frequency limits (e.g., colonoscopy every 10 years)
            # - Specific modifier requirements
            # - Pre-cert requirements

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
