"""Plan-type business rules — referral/PCP, out-of-network, and delegated-billing
logic per health-plan type.

Rules are sourced from HealthCare.gov plan-type definitions and standard managed-care
practice:
  - HMO : PCP gatekeeper + referral for specialists; out-of-network NOT covered (emergency only).
  - POS : PCP + referral for specialists; out-of-network covered at higher cost.
  - IPA : HMO-style (PCP + referral, in-network only); claims route through the IPA / delegated entity.
  - EPO : no PCP/referral; out-of-network NOT covered (emergency only).
  - PPO : no PCP/referral; out-of-network covered at higher cost.
  - Indemnity / Medicare (Original) : any participating provider; no referral.
  - Medicaid : commonly managed-care/HMO-style (varies by state).
  - HDHP : deductible-first; network behavior follows the underlying HMO/PPO design.

These produce advisory findings (referral missing, OON not covered, delegated routing) — they
do not block; the deterministic claim engine still keys off the payer for format/routing.
Ref: https://www.healthcare.gov/choose-a-plan/plan-types/
"""
from __future__ import annotations

from dataclasses import dataclass

from .plan_types import (
    normalize_plan_type,
    HMO, PPO, POS, EPO, IPA, INDEMNITY, HDHP, MEDICARE, MEDICAID, OTHER,
)

# CMS Place-of-Service codes that imply emergency / urgent care (OON still covered).
EMERGENCY_POS_CODES: frozenset[str] = frozenset({"23"})  # 23 = Emergency Room - Hospital


@dataclass(frozen=True)
class PlanRule:
    requires_pcp: bool          # plan uses a PCP gatekeeper
    requires_referral: bool     # specialist visits need a PCP referral
    covers_out_of_network: bool # routine out-of-network care is covered (beyond emergencies)
    delegated_billing: bool     # claims route through a delegated entity (e.g., the IPA)
    notes: str


PLAN_RULES: dict[str, PlanRule] = {
    HMO:       PlanRule(True,  True,  False, False, "In-network only; OON emergency-only; PCP gatekeeper + referrals."),
    POS:       PlanRule(True,  True,  True,  False, "PCP + referral for specialists; OON covered at higher cost."),
    IPA:       PlanRule(True,  True,  False, True,  "HMO-style network; claims route through the IPA / delegated entity."),
    EPO:       PlanRule(False, False, False, False, "No PCP/referral; OON not covered except emergencies."),
    PPO:       PlanRule(False, False, True,  False, "No PCP/referral; OON covered at higher cost."),
    INDEMNITY: PlanRule(False, False, True,  False, "Fee-for-service; any provider; no referral."),
    HDHP:      PlanRule(False, False, True,  False, "Deductible-first; network rules follow the underlying HMO/PPO design."),
    MEDICARE:  PlanRule(False, False, True,  False, "Original Medicare; any participating provider; no referral."),
    MEDICAID:  PlanRule(True,  True,  False, False, "Often managed-care/HMO-style; specifics vary by state."),
    OTHER:     PlanRule(False, False, True,  False, "Unknown plan type; no plan-specific rule applied."),
}


@dataclass(frozen=True)
class PlanRuleFinding:
    severity: str   # "error" | "warning" | "info"
    code: str
    message: str
    suggestion: str | None = None


def get_plan_rule(plan_type: str | None) -> PlanRule | None:
    """Return the PlanRule for a (raw or canonical) plan type, or None if unmapped."""
    canonical = normalize_plan_type(plan_type)
    if canonical is None:
        return None
    return PLAN_RULES.get(canonical)


def evaluate_plan_type_rules(
    *,
    plan_type: str | None,
    network_status: str | None = None,      # "in-network" | "out-of-network" | "unknown"
    referral_on_file: bool | None = None,
    is_specialist: bool | None = None,
    place_of_service: str | None = None,    # CMS POS code (e.g. "11", "23")
    is_emergency: bool | None = None,
) -> list[PlanRuleFinding]:
    """Apply plan-type rules to an encounter/claim context and return advisory findings.

    No-ops (returns []) when the plan type is unknown/unmapped so it is safe to call
    on any claim. Inputs are best-effort; missing context simply yields fewer findings.
    """
    rule = get_plan_rule(plan_type)
    if rule is None:
        return []

    findings: list[PlanRuleFinding] = []
    canonical = normalize_plan_type(plan_type)
    emergency = is_emergency if is_emergency is not None else (
        (place_of_service or "").strip() in EMERGENCY_POS_CODES
    )
    oon = (network_status or "").strip().lower() in ("out-of-network", "out of network", "oon")

    # 1) Out-of-network handling.
    if oon and not emergency:
        if not rule.covers_out_of_network:
            findings.append(PlanRuleFinding(
                severity="error",
                code="PLAN_OON_NOT_COVERED",
                message=f"{canonical} plan: out-of-network provider. {canonical} does not cover routine "
                        f"out-of-network care (emergencies only) — this claim will likely deny.",
                suggestion="Refer the patient to an in-network provider, or document the emergency/authorized "
                           "exception before billing.",
            ))
        else:
            findings.append(PlanRuleFinding(
                severity="info",
                code="PLAN_OON_HIGHER_COST",
                message=f"{canonical} plan: out-of-network provider. Covered at the higher OON benefit level "
                        f"(higher patient cost-share).",
                suggestion="Verify OON benefits and patient responsibility before billing.",
            ))

    # 2) Referral / PCP gatekeeper.
    if rule.requires_referral and is_specialist and referral_on_file is False:
        findings.append(PlanRuleFinding(
            severity="warning",
            code="PLAN_REFERRAL_REQUIRED",
            message=f"{canonical} plan requires a PCP referral for specialist visits, but no referral is on file.",
            suggestion="Obtain and attach the PCP referral/authorization before submitting to avoid denial.",
        ))

    # 3) Delegated billing (IPA and similar).
    if rule.delegated_billing:
        findings.append(PlanRuleFinding(
            severity="info",
            code="PLAN_DELEGATED_BILLING",
            message=f"{canonical}: claims are typically adjudicated by the delegated entity (the IPA/medical group), "
                    f"not the health plan directly.",
            suggestion="Confirm the claim is routed to the delegated payer/IPA per the provider agreement.",
        ))

    return findings
