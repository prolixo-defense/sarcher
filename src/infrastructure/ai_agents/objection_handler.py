"""
RAG + LLM based objection response generator.

Flow:
1. Receive classified reply (from SentimentAnalyzer)
2. Search RAG store for relevant rebuttals matching the objection type
3. Include lead context (company, role, industry, previous messages)
4. Prompt LLM to generate a personalized, empathetic response
5. Return draft response (ALWAYS requires human approval)
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ObjectionHandler:
    """Generates personalized responses to prospect objections using RAG + LLM."""

    def __init__(self, rag_store, llm_client, settings=None):
        self._rag = rag_store
        self._llm = llm_client
        if settings is None:
            from src.infrastructure.config.settings import get_settings
            settings = get_settings()
        self._settings = settings

    async def generate_response(
        self,
        incoming_message: str,
        sentiment: dict,
        lead,
        conversation_history: Optional[list] = None,
    ) -> dict:
        """
        Generate a draft response to an objection or positive reply.

        Returns:
        {
            draft_response: str,
            confidence: float,
            sources: list[str],
            requires_human_review: bool,
        }
        """
        sentiment_type = sentiment.get("sentiment", "NEUTRAL_QUESTION")
        objection_category = self._map_to_category(sentiment_type)

        # 1. Search RAG for relevant rebuttals
        rag_results = []
        if objection_category:
            rag_results = await self._rag.search(
                query=incoming_message,
                category=objection_category,
                top_k=3,
            )
        # Also search without category filter for general matches
        general_results = await self._rag.search(query=incoming_message, top_k=2)
        all_results = rag_results + [r for r in general_results if r not in rag_results]
        sources = [r.get("metadata", {}).get("source", "kb") for r in all_results]

        # 2. Build context from RAG
        rag_context = "\n\n".join(r["text"][:500] for r in all_results[:3]) if all_results else ""

        # 3. Build conversation history
        history_text = ""
        if conversation_history:
            history_text = "\n\nPrevious conversation:\n" + "\n---\n".join(
                [str(m) for m in conversation_history[-4:]]
            )

        # 4. Construct prompt
        system_prompt = (
            "You are a friendly, professional sales development representative. "
            "Write a concise, empathetic email response to the prospect's message. "
            "Do NOT be pushy. The response should be 3-5 sentences maximum. "
            "Personalise it using their name and company. "
            "End with a single soft call-to-action."
        )

        user_prompt = (
            f"Prospect: {lead.full_name()} at {lead.company_name or 'their company'}"
            f" ({lead.job_title or 'unknown role'})\n\n"
            f"Their message:\n{incoming_message}\n\n"
            f"Sentiment analysis: {sentiment_type} — {sentiment.get('summary', '')}"
            f"{history_text}\n\n"
            f"Knowledge base context:\n{rag_context}\n\n"
            "Write a draft reply:"
        )

        # 5. Generate with LLM
        try:
            from pydantic import BaseModel

            class DraftReply(BaseModel):
                draft: str
                confidence: float

            result = await self._llm.extract_structured(
                content=user_prompt,
                response_model=DraftReply,
                system_prompt=system_prompt,
                max_retries=2,
            )
            draft = result.draft
            confidence = result.confidence
        except Exception as exc:
            logger.warning("[ObjectionHandler] LLM failed: %s — using template", exc)
            draft = self._fallback_draft(lead, sentiment_type)
            confidence = 0.4

        return {
            "draft_response": draft,
            "confidence": confidence,
            "sources": sources,
            "requires_human_review": True,  # Always true for MVP
        }

    def _map_to_category(self, sentiment: str) -> Optional[str]:
        """Map sentiment type to RAG category."""
        mapping = {
            "NEGATIVE_BUDGET": "budget",
            "NEGATIVE_TIMING": "timing",
            "NEGATIVE_COMPETITOR": "competitor",
            "NEGATIVE_NOT_INTERESTED": None,
            "NEUTRAL_QUESTION": None,
            "POSITIVE_INTERESTED": None,
            "POSITIVE_REFERRAL": None,
        }
        return mapping.get(sentiment)

    def _fallback_draft(self, lead, sentiment_type: str) -> str:
        name = lead.first_name or "there"
        if "TIMING" in sentiment_type:
            return (
                f"Hi {name}, totally understand the timing might not be right. "
                "Would it be okay if I followed up in a few months? No pressure at all."
            )
        if "BUDGET" in sentiment_type:
            return (
                f"Hi {name}, that's completely fair. Many of our clients started small "
                "and scaled up. Would you be open to a quick call to explore if there's "
                "a fit at a lower commitment level?"
            )
        return (
            f"Hi {name}, thanks for getting back to me. I'd love to address any concerns "
            "you might have. Would a quick 15-minute call work this week?"
        )
