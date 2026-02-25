"""
LLM-powered sentiment/intent classifier for prospect replies.

Uses local Ollama (same model as Phase 3 extraction) — zero cost.

Categories:
  POSITIVE_INTERESTED, POSITIVE_REFERRAL, NEUTRAL_QUESTION,
  NEGATIVE_TIMING, NEGATIVE_BUDGET, NEGATIVE_COMPETITOR,
  NEGATIVE_NOT_INTERESTED, OPT_OUT, AUTO_REPLY, BOUNCE
"""
import logging
from typing import Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SentimentResult(BaseModel):
    sentiment: str = Field(
        description=(
            "One of: POSITIVE_INTERESTED, POSITIVE_REFERRAL, NEUTRAL_QUESTION, "
            "NEGATIVE_TIMING, NEGATIVE_BUDGET, NEGATIVE_COMPETITOR, "
            "NEGATIVE_NOT_INTERESTED, OPT_OUT, AUTO_REPLY, BOUNCE"
        )
    )
    confidence: float = Field(ge=0.0, le=1.0)
    summary: str = Field(description="1-2 sentence summary of the reply")
    suggested_action: str = Field(
        description="One of: reply, wait, escalate, stop, opt_out"
    )
    urgency: str = Field(description="One of: immediate, normal, low")


class SentimentAnalyzer:
    """LLM-powered analysis of prospect replies."""

    # Fast opt-out keyword check (always honoured, even before LLM)
    OPT_OUT_KEYWORDS = [
        "unsubscribe", "remove me", "stop emailing", "stop contacting",
        "opt out", "opt-out", "do not contact", "don't contact", "take me off",
        "please remove", "not interested", "leave me alone",
    ]

    def __init__(self, settings=None):
        if settings is None:
            from src.infrastructure.config.settings import get_settings
            settings = get_settings()
        self._settings = settings

    async def analyze(
        self,
        message_body: str,
        conversation_history: Optional[list[str]] = None,
    ) -> dict:
        """
        Classify a prospect reply.

        Returns {sentiment, confidence, summary, suggested_action, urgency}.
        """
        # Quick keyword check for opt-out (legal requirement — must be instant)
        lower_body = message_body.lower()
        for kw in self.OPT_OUT_KEYWORDS:
            if kw in lower_body:
                return {
                    "sentiment": "OPT_OUT",
                    "confidence": 0.99,
                    "summary": "Prospect has asked to be removed from contact.",
                    "suggested_action": "opt_out",
                    "urgency": "immediate",
                }

        # Check for bounce patterns
        bounce_markers = ["mailer-daemon", "delivery status notification", "undeliverable"]
        for marker in bounce_markers:
            if marker in lower_body:
                return {
                    "sentiment": "BOUNCE",
                    "confidence": 0.95,
                    "summary": "Email delivery failed (bounce).",
                    "suggested_action": "stop",
                    "urgency": "immediate",
                }

        # LLM classification
        try:
            from src.infrastructure.llm.llm_client import LLMClient

            history_text = ""
            if conversation_history:
                history_text = "\n\nPrevious messages:\n" + "\n---\n".join(conversation_history[-3:])

            system_prompt = (
                "You are an expert sales analyst. Classify the following prospect reply "
                "into one of the sentiment categories and provide analysis. "
                "Be conservative — if they hint at opt-out, classify as OPT_OUT."
            )
            user_message = (
                f"Prospect reply to analyze:{history_text}\n\n"
                f"Current message:\n{message_body[:2000]}"
            )

            client = LLMClient(settings=self._settings)
            result = await client.extract_structured(
                content=user_message,
                response_model=SentimentResult,
                system_prompt=system_prompt,
                max_retries=2,
            )
            return result.model_dump()

        except Exception as exc:
            logger.warning("[SentimentAnalyzer] LLM failed: %s — using heuristic", exc)
            return self._heuristic_classify(message_body)

    def _heuristic_classify(self, text: str) -> dict:
        """Simple keyword-based fallback when LLM is unavailable."""
        lower = text.lower()
        if any(w in lower for w in ["interested", "yes", "love to", "sounds good", "tell me more"]):
            return {
                "sentiment": "POSITIVE_INTERESTED",
                "confidence": 0.7,
                "summary": "Prospect seems interested.",
                "suggested_action": "reply",
                "urgency": "normal",
            }
        if any(w in lower for w in ["out of office", "vacation", "away until", "auto-reply"]):
            return {
                "sentiment": "AUTO_REPLY",
                "confidence": 0.9,
                "summary": "Auto-reply / out of office.",
                "suggested_action": "wait",
                "urgency": "low",
            }
        return {
            "sentiment": "NEUTRAL_QUESTION",
            "confidence": 0.5,
            "summary": "Reply received — manual review recommended.",
            "suggested_action": "reply",
            "urgency": "normal",
        }
