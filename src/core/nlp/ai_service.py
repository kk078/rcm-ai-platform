"""
AI Service — Ollama Cloud API integration with RAG pipeline.
Handles all LLM interactions with PHI redaction, prompt management,
token tracking, and structured output parsing.
"""

import json
import structlog
import time
from typing import Any

from ollama import Client
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
    Central AI service managing all Ollama Cloud API interactions.
    Implements RAG pattern with vector store retrieval.
    Falls back to secondary model if primary fails.
    """

    def __init__(self):
        self.client = Client(
            host="https://ollama.com",
            headers={"Authorization": f"Bearer {settings.ollama_api_key}"},
        )
        self.model = settings.ollama_model
        self.fallback_model = settings.ollama_fallback_model
        self.temperature = settings.ollama_temperature
        self.redactor = PHIRedactor()
        self.vector_store = VectorStoreService()
        self.prompts = PromptTemplates()

    async def _call_llm(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """
        Make an Ollama Cloud API call with PHI redaction and error handling.
        Falls back to secondary model if primary fails.
        """
        request_id = str(uuid4())
        start_time = time.time()

        # Redact PHI before sending to API
        redaction_map = {}
        if settings.phi_redaction_enabled:
            user_message, redaction_map = self.redactor.redact(user_message)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        options = {"temperature": temperature or self.temperature}
        if max_tokens:
            options["num_predict"] = max_tokens

        for attempt_model in [self.model, self.fallback_model]:
            try:
                response = self.client.chat(
                    model=attempt_model,
                    messages=messages,
                    options=options,
                )

                result_text = response["message"]["content"]
                duration_ms = round((time.time() - start_time) * 1000, 2)

                # Estimate token usage (Ollama doesn't return exact counts)
                estimated_input = len(system_prompt.split()) + len(user_message.split())
                estimated_output = len(result_text.split())

                logger.info(
                    "ai_api_call",
                    request_id=request_id,
                    model=attempt_model,
                    input_tokens=estimated_input,
                    output_tokens=estimated_output,
                    duration_ms=duration_ms,
                )

                # Re-hydrate PHI in response if redacted
                if settings.phi_redaction_enabled:
                    result_text = self.redactor.rehydrate(result_text, redaction_map)

                return result_text

            except Exception as e:
                if attempt_model == self.model:
                    logger.warning("ai_primary_model_failed", request_id=request_id, error=str(e), fallback=True)
                    continue
                logger.error("ai_api_error", request_id=request_id, error=str(e))
                raise

        # Should not reach here, but just in case
        raise RuntimeError("All AI model attempts failed")

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
        guidelines = await self.vector_store.search(
            collection="icd10_guidelines",
            query=clinical_text[:500],
            limit=10,
        )

        system_prompt = self.prompts.coding_system_prompt()
        user_message = self.prompts.coding_user_prompt(
            clinical_text=clinical_text,
            encounter_type=encounter_type,
            place_of_service=place_of_service,
            patient_age=patient_age,
            patient_gender=patient_gender,
            guidelines_context=guidelines,
        )

        response = await self._call_llm(system_prompt, user_message)
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

        response = await self._call_llm(system_prompt, user_message)
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

        response = await self._call_llm(
            system_prompt, user_message,
            max_tokens=8192,
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
        """
        system_prompt = self.prompts.claim_risk_system_prompt()
        user_message = self.prompts.claim_risk_user_prompt(
            claim_data=claim_data,
            payer_name=payer_name,
            historical_denials=historical_denials,
        )

        response = await self._call_llm(system_prompt, user_message)
        return self._parse_scrub_insight(response)

    # ── Response Parsers ─────────────────────────────────────

    def _parse_coding_response(self, response: str) -> AICodingResponse:
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
        """Extract JSON from model response, handling markdown code fences."""
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        return text.strip()