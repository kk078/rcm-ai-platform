"""
AI Service — Claude API integration with RAG pipeline.
Handles all LLM interactions with PHI redaction, prompt management,
token tracking, and structured output parsing.
"""

import anthropic
import structlog
import time
import json
from typing import Any
from pydantic import BaseModel, Field
from uuid import UUID, uuid4

from src.config import get_settings
from src.core.nlp.phi_redaction import PHIRedactor
from src.core.nlp.vector_store import VectorStoreService
from src.core.nlp.prompts import PromptTemplates

logger = structlog.get_logger()
settings = get_settings()


# ── Response Models ──────────────────────────────────────────────

class AICodeSuggestion(BaseModel):
    code: str
    code_system: str
    description: str
    confidence: float
    rationale: str
    supporting_text: str
    guideline_reference: str | None = None


class AICodingResponse(BaseModel):
    diagnoses: list[AICodeSuggestion]
    procedures: list[AICodeSuggestion]
    entities_extracted: dict
    reasoning: str


class AIAppealResponse(BaseModel):
    letter_content: str
    guidelines_cited: list[str]
    confidence: float
    key_arguments: list[str]


class AIDenialClassification(BaseModel):
    category: str
    subcategory: str
    root_cause: str
    recommended_action: str
    appeal_viable: bool
    recovery_probability: float


class AIClaimScrubInsight(BaseModel):
    risk_factors: list[str]
    suggestions: list[str]
    denial_probability: float
    reasoning: str


# ── Main AI Service ──────────────────────────────────────────────

class AIService:
    """
    Central AI service managing all Claude API interactions.
    Implements RAG pattern with vector store retrieval.
    """

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.anthropic_model
        self.max_tokens = settings.anthropic_max_tokens
        self.temperature = settings.anthropic_temperature
        self.redactor = PHIRedactor()
        self.vector_store = VectorStoreService()
        self.prompts = PromptTemplates()

    async def _call_claude(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """
        Make a Claude API call with PHI redaction, token tracking, and error handling.
        """
        request_id = str(uuid4())
        start_time = time.time()

        # Redact PHI before sending to API
        if settings.phi_redaction_enabled:
            user_message, redaction_map = self.redactor.redact(user_message)

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens or self.max_tokens,
                temperature=temperature or self.temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )

            result_text = response.content[0].text
            duration_ms = round((time.time() - start_time) * 1000, 2)

            # Log usage (no PHI in logs)
            logger.info(
                "ai_api_call",
                request_id=request_id,
                model=self.model,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                duration_ms=duration_ms,
            )

            # Re-hydrate PHI in response if redacted
            if settings.phi_redaction_enabled:
                result_text = self.redactor.rehydrate(result_text, redaction_map)

            return result_text

        except anthropic.APIError as e:
            logger.error("ai_api_error", request_id=request_id, error=str(e))
            raise

    # ── Medical Coding ───────────────────────────────────────

    async def suggest_codes(
        self,
        clinical_text: str,
        encounter_type: str,
        place_of_service: str,
        patient_age: int | None = None,
        patient_gender: str | None = None,
    ) -> AICodingResponse:
        """
        Analyze clinical documentation and suggest medical codes.
        Uses RAG to ground suggestions in official coding guidelines.
        """
        # Step 1: Retrieve relevant coding guidelines from vector DB
        guidelines = await self.vector_store.search(
            collection="icd10_guidelines",
            query=clinical_text[:500],  # Use first 500 chars as search query
            limit=10,
        )

        # Step 2: Build prompt with RAG context
        system_prompt = self.prompts.coding_system_prompt()
        user_message = self.prompts.coding_user_prompt(
            clinical_text=clinical_text,
            encounter_type=encounter_type,
            place_of_service=place_of_service,
            patient_age=patient_age,
            patient_gender=patient_gender,
            guidelines_context=guidelines,
        )

        # Step 3: Call Claude
        response = await self._call_claude(system_prompt, user_message)

        # Step 4: Parse structured response
        return self._parse_coding_response(response)

    # ── Denial Classification ────────────────────────────────

    async def classify_denial(
        self,
        claim_summary: dict,
        denial_reason_code: str,
        denial_remark_codes: list[str],
        payer_name: str,
        clinical_context: str | None = None,
    ) -> AIDenialClassification:
        """
        AI-powered denial root cause analysis.
        """
        # Retrieve relevant payer policies
        policies = await self.vector_store.search(
            collection="payer_policies",
            query=f"{payer_name} {denial_reason_code} denial policy",
            limit=5,
        )

        system_prompt = self.prompts.denial_classification_system_prompt()
        user_message = self.prompts.denial_classification_user_prompt(
            claim_summary=claim_summary,
            reason_code=denial_reason_code,
            remark_codes=denial_remark_codes,
            payer_name=payer_name,
            clinical_context=clinical_context,
            policy_context=policies,
        )

        response = await self._call_claude(system_prompt, user_message)
        return self._parse_denial_classification(response)

    # ── Appeal Generation ────────────────────────────────────

    async def generate_appeal(
        self,
        denial_info: dict,
        claim_info: dict,
        clinical_documentation: str,
        payer_name: str,
        appeal_level: int = 1,
        previous_appeals: list[dict] | None = None,
    ) -> AIAppealResponse:
        """
        Generate a compelling, compliant appeal letter.
        Uses RAG over policies, guidelines, and successful appeal templates.
        """
        # Multi-query vector search for comprehensive context
        policy_context = await self.vector_store.search(
            collection="payer_policies",
            query=f"{payer_name} appeal {denial_info.get('reason_code', '')}",
            limit=5,
        )

        guideline_context = await self.vector_store.search(
            collection="icd10_guidelines",
            query=clinical_documentation[:300],
            limit=5,
        )

        appeal_templates = await self.vector_store.search(
            collection="appeal_templates",
            query=f"{denial_info.get('category', '')} {denial_info.get('reason_code', '')}",
            limit=3,
        )

        system_prompt = self.prompts.appeal_generation_system_prompt(appeal_level)
        user_message = self.prompts.appeal_generation_user_prompt(
            denial_info=denial_info,
            claim_info=claim_info,
            clinical_documentation=clinical_documentation,
            payer_name=payer_name,
            policy_context=policy_context,
            guideline_context=guideline_context,
            appeal_templates=appeal_templates,
            previous_appeals=previous_appeals,
        )

        response = await self._call_claude(
            system_prompt, user_message,
            max_tokens=8192,  # Appeals need more tokens
            temperature=0.2,
        )
        return self._parse_appeal_response(response)

    # ── Claim Scrub Intelligence ─────────────────────────────

    async def analyze_claim_risk(
        self,
        claim_data: dict,
        payer_name: str,
        historical_denials: list[dict] | None = None,
    ) -> AIClaimScrubInsight:
        """
        AI analysis of claim denial risk beyond rule-based scrubbing.
        Considers payer patterns, historical data, and clinical context.
        """
        system_prompt = self.prompts.claim_risk_system_prompt()
        user_message = self.prompts.claim_risk_user_prompt(
            claim_data=claim_data,
            payer_name=payer_name,
            historical_denials=historical_denials,
        )

        response = await self._call_claude(system_prompt, user_message)
        return self._parse_scrub_insight(response)

    # ── Response Parsers ─────────────────────────────────────

    def _parse_coding_response(self, response: str) -> AICodingResponse:
        """Parse Claude's coding response into structured format."""
        try:
            data = json.loads(self._extract_json(response))
            return AICodingResponse(**data)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("coding_parse_error", error=str(e), response_preview=response[:200])
            raise ValueError(f"Failed to parse coding response: {e}")

    def _parse_denial_classification(self, response: str) -> AIDenialClassification:
        try:
            data = json.loads(self._extract_json(response))
            return AIDenialClassification(**data)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("denial_parse_error", error=str(e))
            raise ValueError(f"Failed to parse denial classification: {e}")

    def _parse_appeal_response(self, response: str) -> AIAppealResponse:
        try:
            data = json.loads(self._extract_json(response))
            return AIAppealResponse(**data)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("appeal_parse_error", error=str(e))
            raise ValueError(f"Failed to parse appeal response: {e}")

    def _parse_scrub_insight(self, response: str) -> AIClaimScrubInsight:
        try:
            data = json.loads(self._extract_json(response))
            return AIClaimScrubInsight(**data)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("scrub_parse_error", error=str(e))
            raise ValueError(f"Failed to parse scrub insight: {e}")

    @staticmethod
    def _extract_json(text: str) -> str:
        """Extract JSON from Claude's response, handling markdown code fences."""
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        return text.strip()
