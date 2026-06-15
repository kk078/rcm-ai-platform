"""
AI Service — dual-provider LLM integration with RAG pipeline.

Provider selection via AI_PROVIDER env var (default: "ollama"):
  AI_PROVIDER=ollama      → Ollama Cloud (qwen3-coder:480b-cloud / deepseek-v3.1:671b-cloud)
  AI_PROVIDER=anthropic   → Anthropic Claude (claude-sonnet-4-6 / claude-opus-4-6)

Both providers share the same interface, semaphore-controlled concurrency (50 max),
PHI redaction, structured JSON output, and streaming support.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncGenerator
from uuid import uuid4

import structlog
from pydantic import BaseModel, Field

from src.config import get_settings
from src.core.nlp.phi_redaction import PHIRedactor
from src.core.nlp.prompts import PromptTemplates

logger = structlog.get_logger()
settings = get_settings()

# Global semaphore — max 50 simultaneous LLM calls across the process
_LLM_SEMAPHORE: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _LLM_SEMAPHORE
    if _LLM_SEMAPHORE is None:
        limit = (
            settings.anthropic_max_concurrent
            if settings.ai_provider == "anthropic"
            else 50
        )
        _LLM_SEMAPHORE = asyncio.Semaphore(limit)
    return _LLM_SEMAPHORE


# ── Response Models ──────────────────────────────────────────────────────────

class AICodeSuggestion(BaseModel):
    code: str
    code_system: str
    description: str
    confidence: float = 0.0
    rationale: str = ""
    supporting_text: str = ""
    guideline_reference: str | None = None


class AICodingResponse(BaseModel):
    diagnoses: list[AICodeSuggestion] = Field(default_factory=list)
    procedures: list[AICodeSuggestion] = Field(default_factory=list)
    entities_extracted: dict = Field(default_factory=dict)
    reasoning: str = ""


class AIAppealResponse(BaseModel):
    letter_content: str
    guidelines_cited: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    key_arguments: list[str] = Field(default_factory=list)


class AIDenialClassification(BaseModel):
    category: str
    subcategory: str = ""
    root_cause: str = ""
    recommended_action: str = ""
    appeal_viable: bool = True
    recovery_probability: float = 0.5


class AIClaimScrubInsight(BaseModel):
    risk_factors: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    denial_probability: float = 0.0
    reasoning: str = ""


class AIChatResponse(BaseModel):
    message: str
    session_id: str
    tokens_used: int = 0


# ── Provider Backend ─────────────────────────────────────────────────────────

class _OllamaBackend:
    """Ollama Cloud backend — uses qwen3-coder:480b-cloud as primary."""

    def __init__(self):
        from ollama import AsyncClient
        self._client = AsyncClient(
            host=settings.ollama_base_url,
            headers={"Authorization": f"Bearer {settings.ollama_api_key}"}
            if settings.ollama_api_key else {},
        )
        self.model = settings.ollama_model
        self.model_heavy = settings.ollama_model          # same model for heavy tasks
        self.fallback = settings.ollama_fallback_model

    async def call(self, system: str, user_content: str, model: str | None = None,
                   max_tokens: int = 4096, use_json: bool = True) -> tuple[str, int]:
        """Single call with semaphore. Returns (text, tokens)."""
        target = model or self.model
        messages = [
            {"role": "system", "content": system},
            {"role": "user",   "content": user_content},
        ]
        opts: dict = {"temperature": settings.ollama_temperature, "num_predict": max_tokens}

        async with _get_semaphore():
            try:
                resp = await self._client.chat(
                    model=target,
                    messages=messages,
                    format="json" if use_json else "",
                    options=opts,
                )
                text = resp.message.content or ""
                tokens = (resp.prompt_eval_count or 0) + (resp.eval_count or 0)
                return text, tokens
            except Exception:
                # Retry with fallback model
                resp = await self._client.chat(
                    model=self.fallback,
                    messages=messages,
                    format="json" if use_json else "",
                    options=opts,
                )
                text = resp.message.content or ""
                tokens = (resp.prompt_eval_count or 0) + (resp.eval_count or 0)
                return text, tokens

    async def stream(self, system: str, user_content: str,
                     model: str | None = None) -> AsyncGenerator[str, None]:
        messages = [
            {"role": "system", "content": system},
            {"role": "user",   "content": user_content},
        ]
        async with _get_semaphore():
            async for chunk in await self._client.chat(
                model=model or self.model,
                messages=messages,
                stream=True,
                options={"temperature": settings.ollama_temperature},
            ):
                if chunk.message and chunk.message.content:
                    yield chunk.message.content


class _AnthropicBackend:
    """Anthropic Claude backend — claude-sonnet-4-6 primary, claude-opus-4-6 heavy."""

    def __init__(self):
        import anthropic as anthropic_lib
        self._client = anthropic_lib.AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            max_retries=settings.anthropic_max_retries,
            timeout=settings.anthropic_timeout,
        )
        self.model = settings.anthropic_model
        self.model_heavy = settings.anthropic_model_heavy

    async def call(self, system: str, user_content: str, model: str | None = None,
                   max_tokens: int | None = None, use_json: bool = True) -> tuple[str, int]:
        async with _get_semaphore():
            resp = await self._client.messages.create(
                model=model or self.model,
                max_tokens=max_tokens or settings.anthropic_max_tokens,
                temperature=settings.anthropic_temperature,
                system=system,
                messages=[{"role": "user", "content": user_content}],
            )
            text = resp.content[0].text if resp.content else ""
            tokens = resp.usage.input_tokens + resp.usage.output_tokens
            return text, tokens

    async def stream(self, system: str, user_content: str,
                     model: str | None = None) -> AsyncGenerator[str, None]:
        async with _get_semaphore():
            async with self._client.messages.stream(
                model=model or self.model,
                max_tokens=settings.anthropic_max_tokens,
                temperature=settings.anthropic_temperature,
                system=system,
                messages=[{"role": "user", "content": user_content}],
            ) as s:
                async for text in s.text_stream:
                    yield text


def _make_backend() -> _OllamaBackend | _AnthropicBackend:
    provider = settings.ai_provider.lower()
    if provider == "anthropic":
        logger.info("ai_provider", provider="anthropic", model=settings.anthropic_model)
        return _AnthropicBackend()
    logger.info("ai_provider", provider="ollama", model=settings.ollama_model)
    return _OllamaBackend()


# ── Main AI Service ──────────────────────────────────────────────────────────

class AIService:
    """
    Provider-agnostic AI service for all RCM LLM tasks.
    Switch providers by setting AI_PROVIDER=ollama (default) or AI_PROVIDER=anthropic.
    """

    def __init__(self):
        self._backend: _OllamaBackend | _AnthropicBackend | None = None
        self.phi_redactor = PHIRedactor()
        self.prompts = PromptTemplates()

    @property
    def model(self) -> str:
        return self._get_backend().model

    def _get_backend(self) -> _OllamaBackend | _AnthropicBackend:
        if self._backend is None:
            self._backend = _make_backend()
        return self._backend

    def _heavy_model(self) -> str:
        return self._get_backend().model_heavy

    # ── Medical Coding ───────────────────────────────────────────────────────

    async def suggest_codes(
        self,
        clinical_text: str,
        encounter_type: str | None = None,
        place_of_service: str | None = None,
        patient_age: int | None = None,
        patient_gender: str | None = None,
    ) -> AICodingResponse:
        """Extract ICD-10-CM and CPT codes from clinical text."""
        redacted = self.phi_redactor.redact(clinical_text)

        system = (
            "You are an expert AAPC-certified medical coder with deep knowledge of ICD-10-CM, "
            "CPT, and HCPCS coding guidelines. Analyze clinical documentation and suggest accurate "
            "medical codes following CMS rules and payer requirements. "
            "Respond ONLY with valid JSON — no markdown, no commentary outside the JSON."
        )

        context = "\n".join(filter(None, [
            f"Encounter Type: {encounter_type}" if encounter_type else "",
            f"Place of Service: {place_of_service}" if place_of_service else "",
            f"Patient Age: {patient_age} years" if patient_age is not None else "",
            f"Patient Gender: {patient_gender}" if patient_gender else "",
        ]))

        user_content = f"""Analyze this clinical documentation and provide accurate medical codes.

ENCOUNTER CONTEXT:
{context}

CLINICAL DOCUMENTATION:
{redacted}

Return this exact JSON structure:
{{
  "diagnoses": [
    {{
      "code": "ICD-10-CM code",
      "code_system": "ICD-10-CM",
      "description": "Code description",
      "confidence": 0.95,
      "rationale": "Clinical reasoning",
      "supporting_text": "Text from documentation",
      "guideline_reference": "Guideline reference or null"
    }}
  ],
  "procedures": [
    {{
      "code": "CPT or HCPCS code",
      "code_system": "CPT",
      "description": "Procedure description",
      "confidence": 0.90,
      "rationale": "Rationale",
      "supporting_text": "Supporting text",
      "guideline_reference": null
    }}
  ],
  "entities_extracted": {{
    "diagnoses_mentioned": [],
    "procedures_mentioned": [],
    "medications": [],
    "lab_values": {{}},
    "vital_signs": {{}}
  }},
  "reasoning": "Overall coding rationale"
}}"""

        try:
            text, tokens = await self._get_backend().call(
                system=system, user_content=user_content,
                model=self._heavy_model(), max_tokens=4096,
            )
            data = _extract_json(text)
            response = AICodingResponse(
                diagnoses=[AICodeSuggestion(**d) for d in data.get("diagnoses", [])],
                procedures=[AICodeSuggestion(**p) for p in data.get("procedures", [])],
                entities_extracted=data.get("entities_extracted", {}),
                reasoning=data.get("reasoning", ""),
            )
            logger.info("ai_coding_complete", provider=settings.ai_provider, tokens=tokens,
                       dx=len(response.diagnoses), proc=len(response.procedures))
            return response
        except Exception as e:
            logger.error("ai_coding_failed", error=str(e))
            raise

    async def suggest_codes_batch(
        self, cases: list[dict],
    ) -> list[AICodingResponse | Exception]:
        """Process up to 50 coding cases concurrently."""
        tasks = [
            self.suggest_codes(
                clinical_text=c.get("clinical_text", ""),
                encounter_type=c.get("encounter_type"),
                place_of_service=c.get("place_of_service"),
                patient_age=c.get("patient_age"),
                patient_gender=c.get("patient_gender"),
            )
            for c in cases
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok = sum(1 for r in results if not isinstance(r, Exception))
        logger.info("batch_coding_complete", total=len(cases), success=ok, failed=len(cases)-ok)
        return list(results)

    # ── Denial Management ────────────────────────────────────────────────────

    async def classify_denial(
        self,
        denial_reason: str,
        claim_data: dict,
        payer_name: str | None = None,
    ) -> AIDenialClassification:
        """Classify a denial and recommend action."""
        system = (
            "You are a revenue cycle expert specializing in claim denial management. "
            "Respond ONLY with valid JSON."
        )
        payer = f"Payer: {payer_name}" if payer_name else ""
        user_content = f"""Classify this claim denial.

DENIAL REASON: {denial_reason}
{payer}

CLAIM DATA:
{json.dumps(claim_data, indent=2, default=str)[:1500]}

Return:
{{
  "category": "authorization|medical_necessity|coding_error|duplicate|eligibility|timely_filing|coordination_of_benefits|other",
  "subcategory": "specific subcategory",
  "root_cause": "root cause analysis",
  "recommended_action": "specific action to take",
  "appeal_viable": true,
  "recovery_probability": 0.75
}}"""

        try:
            text, tokens = await self._get_backend().call(system=system, user_content=user_content)
            data = _extract_json(text)
            logger.info("denial_classified", tokens=tokens, category=data.get("category"))
            return AIDenialClassification(**data)
        except Exception as e:
            logger.error("denial_classification_failed", error=str(e))
            return AIDenialClassification(
                category="other",
                root_cause=f"Classification failed: {e}",
                recommended_action="Manual review required",
            )

    async def generate_appeal(
        self,
        denial_reason: str,
        clinical_notes: str,
        claim_data: dict,
        payer_name: str | None = None,
        guidelines: list[dict] | None = None,
    ) -> AIAppealResponse:
        """Generate a professional denial appeal letter."""
        redacted = self.phi_redactor.redact(clinical_notes)
        system = (
            "You are an expert medical billing appeals specialist with deep knowledge of "
            "payer policies, medical necessity criteria, and CMS guidelines. "
            "Respond ONLY with valid JSON."
        )
        guidelines_text = ""
        if guidelines:
            guidelines_text = "\n\nRELEVANT GUIDELINES:\n" + "\n".join(
                g.get("content", "") for g in guidelines[:5]
            )
        payer = f"Payer: {payer_name}" if payer_name else ""
        user_content = f"""Generate a professional denial appeal letter.

DENIAL REASON: {denial_reason}
{payer}

CLAIM:
{json.dumps(claim_data, indent=2, default=str)[:1200]}

CLINICAL NOTES:
{redacted[:2500]}
{guidelines_text}

Return:
{{
  "letter_content": "Complete formal appeal letter text",
  "guidelines_cited": ["guideline 1", "guideline 2"],
  "confidence": 0.85,
  "key_arguments": ["argument 1", "argument 2", "argument 3"]
}}"""

        try:
            text, tokens = await self._get_backend().call(
                system=system, user_content=user_content,
                model=self._heavy_model(), max_tokens=6000,
            )
            data = _extract_json(text)
            logger.info("appeal_generated", provider=settings.ai_provider, tokens=tokens)
            return AIAppealResponse(**data)
        except Exception as e:
            logger.error("appeal_generation_failed", error=str(e))
            raise

    async def stream_appeal(
        self,
        denial_reason: str,
        clinical_notes: str,
        claim_data: dict,
        payer_name: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream an appeal letter for real-time display."""
        redacted = self.phi_redactor.redact(clinical_notes)
        system = (
            "You are an expert medical billing appeals specialist. Write a compelling, "
            "professional denial appeal letter. Write the letter directly — no JSON."
        )
        payer = f"Payer: {payer_name}" if payer_name else ""
        user_content = f"""Write a professional appeal letter.

DENIAL: {denial_reason}
{payer}
CLAIM: {json.dumps(claim_data, default=str)[:800]}
CLINICAL NOTES: {redacted[:1500]}

Write the complete formal appeal letter:"""

        async for chunk in self._get_backend().stream(
            system=system, user_content=user_content, model=self._heavy_model()
        ):
            yield chunk

    # ── Claim Risk Analysis ──────────────────────────────────────────────────

    async def analyze_claim_risk(
        self,
        claim_data: dict,
        scrub_findings: list[dict] | None = None,
    ) -> AIClaimScrubInsight:
        """AI-powered pre-submission claim risk analysis."""
        system = (
            "You are a medical billing expert specializing in claim denial prevention. "
            "Respond ONLY with valid JSON."
        )
        findings_text = ""
        if scrub_findings:
            findings_text = f"\nSCRUB FINDINGS:\n{json.dumps(scrub_findings, indent=2)[:800]}"

        user_content = f"""Analyze this claim for denial risk.

CLAIM:
{json.dumps(claim_data, indent=2, default=str)[:1500]}
{findings_text}

Return:
{{
  "risk_factors": ["risk 1", "risk 2"],
  "suggestions": ["fix 1", "fix 2"],
  "denial_probability": 0.25,
  "reasoning": "Overall risk assessment"
}}"""

        try:
            text, tokens = await self._get_backend().call(system=system, user_content=user_content)
            data = _extract_json(text)
            logger.info("claim_risk_analyzed", tokens=tokens, prob=data.get("denial_probability"))
            return AIClaimScrubInsight(**data)
        except Exception as e:
            logger.error("claim_risk_failed", error=str(e))
            return AIClaimScrubInsight(
                risk_factors=["Analysis unavailable"],
                suggestions=["Manual review recommended"],
                denial_probability=0.5,
                reasoning=f"AI analysis failed: {e}",
            )

    async def analyze_claims_batch(
        self, claims: list[dict],
    ) -> list[AIClaimScrubInsight | Exception]:
        """Batch claim risk analysis — up to 50 concurrent."""
        tasks = [self.analyze_claim_risk(c) for c in claims]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("batch_claim_analysis_complete", total=len(claims))
        return list(results)

    # ── Revenue Intelligence ─────────────────────────────────────────────────

    async def generate_revenue_insights(self, analytics_data: dict) -> dict:
        """AI-driven revenue cycle insights from analytics data."""
        system = (
            "You are a healthcare revenue cycle analytics expert. Analyze RCM metrics "
            "and provide specific, actionable insights. Respond ONLY with valid JSON."
        )
        user_content = f"""Analyze this revenue cycle data.

DATA:
{json.dumps(analytics_data, indent=2, default=str)[:2500]}

Return:
{{
  "executive_summary": "2-3 sentence summary",
  "key_insights": [
    {{
      "category": "denials|collections|coding|productivity|payer",
      "finding": "finding",
      "impact": "financial impact",
      "recommendation": "action",
      "priority": "high|medium|low"
    }}
  ],
  "denial_trends": "denial pattern analysis",
  "collection_opportunities": "collection improvement opportunities",
  "coding_accuracy": "coding accuracy assessment",
  "payer_performance": "payer-specific insights",
  "action_plan": ["action 1", "action 2", "action 3"],
  "predicted_improvement": "estimated improvement %"
}}"""

        try:
            text, tokens = await self._get_backend().call(
                system=system, user_content=user_content,
                model=self._heavy_model(), max_tokens=4096,
            )
            data = _extract_json(text)
            logger.info("revenue_insights_generated", tokens=tokens)
            return data
        except Exception as e:
            logger.error("revenue_insights_failed", error=str(e))
            return {"error": str(e), "executive_summary": "Analysis unavailable"}

    # ── AI Chat Assistant ────────────────────────────────────────────────────

    async def chat(
        self,
        messages: list[dict],
        context: str | None = None,
        stream: bool = False,
    ) -> AIChatResponse | AsyncGenerator[str, None]:
        """RCM AI assistant — billing, coding, compliance Q&A."""
        system = """You are Aethera AI, an expert Revenue Cycle Management assistant with deep knowledge of:
- ICD-10-CM, CPT, HCPCS coding guidelines
- Medicare, Medicaid, and commercial payer policies
- Claim submission, denial management, and appeals
- HIPAA compliance and healthcare regulations
- Prior authorization, EOB/ERA interpretation

Be concise, accurate, and actionable. Cite specific guidelines for coding questions."""
        if context:
            system += f"\n\nCONTEXT:\n{context}"

        valid_messages = [
            m for m in messages
            if m.get("role") in ("user", "assistant") and m.get("content")
        ]
        if not valid_messages:
            return AIChatResponse(message="Please provide a message.", session_id=str(uuid4()))

        # For multi-turn, collapse into system + latest user message for Ollama compatibility
        if len(valid_messages) == 1:
            user_content = valid_messages[0]["content"]
        else:
            # Embed conversation history in user message for Ollama
            history = "\n".join(
                f"{'User' if m['role']=='user' else 'Assistant'}: {m['content']}"
                for m in valid_messages[:-1]
            )
            user_content = f"Previous conversation:\n{history}\n\nUser: {valid_messages[-1]['content']}"

        if stream:
            async def _gen():
                async for chunk in self._get_backend().stream(
                    system=system, user_content=user_content
                ):
                    yield chunk
            return _gen()

        try:
            text, tokens = await self._get_backend().call(
                system=system, user_content=user_content, use_json=False, max_tokens=2048,
            )
            return AIChatResponse(message=text, session_id=str(uuid4()), tokens_used=tokens)
        except Exception as e:
            logger.error("ai_chat_failed", error=str(e))
            return AIChatResponse(
                message="I'm temporarily unavailable. Please try again in a moment.",
                session_id=str(uuid4()),
            )

    async def stream_coding_session(
        self, clinical_text: str, encounter_type: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Stream real-time coding analysis."""
        redacted = self.phi_redactor.redact(clinical_text)
        system = (
            "You are an expert AAPC-certified medical coder. Analyze clinical documentation "
            "and provide code suggestions with step-by-step reasoning."
        )
        user_content = f"""Analyze this clinical documentation and suggest ICD-10-CM and CPT codes.
Walk through your reasoning step by step.

ENCOUNTER TYPE: {encounter_type or "Not specified"}

CLINICAL DOCUMENTATION:
{redacted}

Provide your analysis:"""

        async for chunk in self._get_backend().stream(
            system=system, user_content=user_content, model=self._heavy_model()
        ):
            yield chunk


# ── Helpers ──────────────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict:
    """Extract JSON from LLM response, handling markdown code fences."""
    text = text.strip()
    # Strip ```json ... ``` or ``` ... ```
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        raise ValueError(f"Could not parse JSON from LLM response: {text[:300]}")


# Module-level singleton
_ai_service_instance: AIService | None = None


def get_ai_service() -> AIService:
    global _ai_service_instance
    if _ai_service_instance is None:
        _ai_service_instance = AIService()
    return _ai_service_instance
