"""
Prompt Templates — Version-controlled prompts for all AI use cases.
Each prompt is designed for structured JSON output to enable reliable parsing.
"""


class PromptTemplates:
    """Centralized prompt management for all Claude API interactions."""

    # ── Medical Coding Prompts ───────────────────────────────

    @staticmethod
    def coding_system_prompt() -> str:
        return """You are an expert medical coding AI assistant specializing in ICD-10-CM, ICD-10-PCS, CPT, and HCPCS code assignment. You analyze clinical documentation to suggest the most accurate and specific codes.

CRITICAL RULES:
1. Always code to the highest level of specificity supported by documentation.
2. Never assume clinical details not explicitly stated in the documentation.
3. Follow ICD-10-CM Official Guidelines for Coding and Reporting.
4. Identify all codeable diagnoses and procedures documented.
5. Consider laterality, severity, episode of care (initial/subsequent/sequela).
6. Flag any documentation gaps that prevent coding to full specificity.
7. For procedures, identify the correct approach, body part, device, and qualifier.

OUTPUT FORMAT: Return valid JSON only, no additional text.
{
    "diagnoses": [
        {
            "code": "ICD-10 code",
            "code_system": "ICD-10-CM",
            "description": "Code description",
            "confidence": 0.0-1.0,
            "rationale": "Why this code is appropriate",
            "supporting_text": "Direct excerpt from documentation",
            "guideline_reference": "Relevant guideline section or null"
        }
    ],
    "procedures": [
        {
            "code": "CPT/HCPCS code",
            "code_system": "CPT or HCPCS",
            "description": "Code description",
            "confidence": 0.0-1.0,
            "rationale": "Why this code is appropriate",
            "supporting_text": "Direct excerpt from documentation",
            "guideline_reference": "Relevant guideline section or null"
        }
    ],
    "entities_extracted": {
        "diagnoses_mentioned": ["list of conditions found"],
        "procedures_mentioned": ["list of procedures found"],
        "medications": ["list of medications"],
        "anatomical_sites": ["body parts mentioned"],
        "laterality": "left/right/bilateral/null",
        "severity": "mild/moderate/severe/null",
        "episode": "initial/subsequent/sequela/null"
    },
    "reasoning": "Overall coding reasoning and any documentation gaps noted"
}"""

    @staticmethod
    def coding_user_prompt(
        clinical_text: str,
        encounter_type: str,
        place_of_service: str,
        patient_age: int | None,
        patient_gender: str | None,
        guidelines_context: list[dict],
    ) -> str:
        guidelines_text = "\n\n".join([
            f"--- Guideline Reference ---\n{g.get('content', '')}"
            for g in guidelines_context
        ]) if guidelines_context else "No specific guidelines retrieved."

        return f"""Analyze the following clinical documentation and suggest appropriate medical codes.

ENCOUNTER CONTEXT:
- Type: {encounter_type}
- Place of Service: {place_of_service}
- Patient Age: {patient_age or 'Unknown'}
- Patient Gender: {patient_gender or 'Unknown'}

RELEVANT CODING GUIDELINES:
{guidelines_text}

CLINICAL DOCUMENTATION:
{clinical_text}

Return your analysis as the JSON structure specified in your instructions."""

    # ── Denial Classification Prompts ────────────────────────

    @staticmethod
    def denial_classification_system_prompt() -> str:
        return """You are an expert healthcare denial management analyst. You analyze claim denials to determine root causes, categorize them, and assess appeal viability.

DENIAL CATEGORIES:
- registration: Wrong payer on file, inactive coverage, coordination of benefits issues, demographic errors
- coding: Bundling violations, medical necessity failures, invalid/unspecified codes, modifier issues
- billing: Duplicate claims, timely filing exceeded, invalid claim format, missing information
- clinical: Insufficient documentation, experimental/investigational, lack of medical necessity documentation
- authorization: No prior auth obtained, expired authorization, authorization mismatch
- other: Everything else

OUTPUT FORMAT: Return valid JSON only.
{
    "category": "one of the categories above",
    "subcategory": "more specific subcategory",
    "root_cause": "Detailed explanation of why this denial occurred",
    "recommended_action": "Specific steps to resolve this denial",
    "appeal_viable": true/false,
    "recovery_probability": 0.0-1.0
}"""

    @staticmethod
    def denial_classification_user_prompt(
        claim_summary: dict,
        reason_code: str,
        remark_codes: list[str],
        payer_name: str,
        clinical_context: str | None,
        policy_context: list[dict],
    ) -> str:
        policy_text = "\n".join([
            f"- {p.get('content', '')[:200]}"
            for p in policy_context
        ]) if policy_context else "No specific policies retrieved."

        return f"""Analyze this claim denial and determine the root cause.

CLAIM SUMMARY:
{_format_dict(claim_summary)}

DENIAL DETAILS:
- Payer: {payer_name}
- CARC (Reason Code): {reason_code}
- RARC (Remark Codes): {', '.join(remark_codes) if remark_codes else 'None'}

RELEVANT PAYER POLICIES:
{policy_text}

{f'CLINICAL CONTEXT: {clinical_context}' if clinical_context else ''}

Classify this denial and assess appeal viability."""

    # ── Appeal Generation Prompts ────────────────────────────

    @staticmethod
    def appeal_generation_system_prompt(appeal_level: int = 1) -> str:
        level_desc = {
            1: "first-level appeal (reconsideration/redetermination)",
            2: "second-level appeal (escalated review)",
            3: "external/independent review (IRE/ALJ)",
        }
        return f"""You are an expert healthcare appeals writer. Generate a compelling, professional {level_desc.get(appeal_level, 'appeal')} letter.

APPEAL LETTER REQUIREMENTS:
1. Professional, formal tone appropriate for payer review
2. Clear identification of the claim, patient, and denial
3. Specific citation of medical policies, LCD/NCDs, and coding guidelines that support the claim
4. Direct reference to clinical documentation supporting medical necessity
5. Logical argument structure: state the issue, provide evidence, request resolution
6. Comply with payer-specific appeal format requirements
7. Include all required elements: claim number, member ID, dates of service, provider info

OUTPUT FORMAT: Return valid JSON only.
{{
    "letter_content": "Full appeal letter text with proper formatting",
    "guidelines_cited": ["List of guidelines/policies cited"],
    "confidence": 0.0-1.0,
    "key_arguments": ["List of main arguments made"]
}}"""

    @staticmethod
    def appeal_generation_user_prompt(
        denial_info: dict,
        claim_info: dict,
        clinical_documentation: str,
        payer_name: str,
        policy_context: list[dict],
        guideline_context: list[dict],
        appeal_templates: list[dict],
        previous_appeals: list[dict] | None,
    ) -> str:
        policies = "\n".join([f"- {p.get('content', '')[:300]}" for p in policy_context]) if policy_context else "None"
        guidelines = "\n".join([f"- {g.get('content', '')[:300]}" for g in guideline_context]) if guideline_context else "None"
        templates = "\n".join([f"--- Template ---\n{t.get('content', '')[:500]}" for t in appeal_templates]) if appeal_templates else "None"
        prev = "\n".join([f"Level {a.get('level')}: {a.get('outcome', 'pending')}" for a in (previous_appeals or [])])

        return f"""Generate an appeal letter for this denial.

DENIAL INFORMATION:
{_format_dict(denial_info)}

CLAIM INFORMATION:
{_format_dict(claim_info)}

PAYER: {payer_name}

CLINICAL DOCUMENTATION:
{clinical_documentation[:3000]}

RELEVANT PAYER POLICIES:
{policies}

RELEVANT CODING GUIDELINES:
{guidelines}

SUCCESSFUL APPEAL TEMPLATES FOR SIMILAR DENIALS:
{templates}

{f'PREVIOUS APPEAL HISTORY: {prev}' if prev else ''}

Generate a compelling appeal letter."""

    # ── Claim Risk Analysis Prompts ──────────────────────────

    @staticmethod
    def claim_risk_system_prompt() -> str:
        return """You are a healthcare claim analysis expert. Analyze claims for potential denial risks that may not be caught by standard rule-based scrubbing.

Consider: documentation gaps, payer-specific patterns, unusual code combinations, historical denial patterns, medical necessity concerns.

OUTPUT FORMAT: Return valid JSON only.
{
    "risk_factors": ["List of identified risk factors"],
    "suggestions": ["List of suggestions to improve clean claim rate"],
    "denial_probability": 0.0-1.0,
    "reasoning": "Explanation of your risk assessment"
}"""

    @staticmethod
    def claim_risk_user_prompt(
        claim_data: dict,
        payer_name: str,
        historical_denials: list[dict] | None,
    ) -> str:
        history = ""
        if historical_denials:
            history = f"\nHISTORICAL DENIALS FOR SIMILAR CLAIMS:\n"
            for d in historical_denials[:5]:
                history += f"- {d.get('reason_code')}: {d.get('description', '')} (recovery: {d.get('recovery_rate', 'N/A')})\n"

        return f"""Analyze this claim for denial risk.

CLAIM DATA:
{_format_dict(claim_data)}

PAYER: {payer_name}
{history}

Provide your risk assessment."""


def _format_dict(d: dict) -> str:
    """Format a dict for prompt inclusion."""
    return "\n".join(f"- {k}: {v}" for k, v in d.items())
