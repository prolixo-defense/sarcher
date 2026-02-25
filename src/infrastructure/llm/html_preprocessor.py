"""
HTML to clean Markdown preprocessor for LLM consumption.

Removes navigation, ads, scripts and converts the main content to
token-efficient Markdown within a configurable token budget.
"""
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

_TIKTOKEN_ENCODING = "cl100k_base"


class HtmlPreprocessor:
    """
    Converts raw HTML into clean, token-efficient Markdown for LLM consumption.

    Pipeline:
    1. trafilatura extracts main content (removes nav, footer, ads, scripts)
    2. BeautifulSoup fallback if trafilatura returns nothing
    3. markdownify converts cleaned HTML/text to Markdown
    4. Whitespace normalisation (collapse blank lines, strip trailing spaces)
    5. Token-count with tiktoken; truncate to max_tokens budget

    Returns a dict with:
        cleaned_markdown  : str  — token-efficient Markdown
        token_count       : int  — approximate token count
        extraction_method : str  — "trafilatura" or "beautifulsoup"
    """

    def preprocess(self, raw_html: str, max_tokens: int = 4000) -> dict:
        extraction_method = "trafilatura"
        cleaned = self._try_trafilatura(raw_html)

        if not cleaned:
            extraction_method = "beautifulsoup"
            cleaned = self._try_bs4(raw_html)

        markdown = self._to_markdown(cleaned)
        markdown = self._normalize_whitespace(markdown)

        token_count = self._count_tokens(markdown)
        if token_count > max_tokens:
            markdown = self._truncate_to_tokens(markdown, max_tokens)
            token_count = max_tokens

        return {
            "cleaned_markdown": markdown,
            "token_count": token_count,
            "extraction_method": extraction_method,
        }

    # ------------------------------------------------------------------
    # Extraction strategies
    # ------------------------------------------------------------------

    @staticmethod
    def _try_trafilatura(html: str) -> Optional[str]:
        try:
            import trafilatura

            return trafilatura.extract(html, include_tables=True, include_links=True)
        except Exception as exc:
            logger.debug("trafilatura extraction failed: %s", exc)
            return None

    @staticmethod
    def _try_bs4(html: str) -> str:
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "lxml")

            # Remove noise tags
            for tag in soup.find_all(
                ["script", "style", "nav", "footer", "header", "noscript"]
            ):
                tag.decompose()

            # Remove hidden elements
            for tag in soup.find_all(style=True):
                style = tag.get("style", "").replace(" ", "")
                if "display:none" in style or "visibility:hidden" in style:
                    tag.decompose()

            # Prefer specific content containers
            for selector in [
                "main",
                "article",
                "[id*='content']",
                "[class*='content']",
                "body",
            ]:
                elements = soup.select(selector)
                if elements:
                    return str(elements[0])

            return str(soup)
        except Exception as exc:
            logger.debug("BeautifulSoup extraction failed: %s", exc)
            return html

    # ------------------------------------------------------------------
    # Conversion helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_markdown(content: str) -> str:
        if not content:
            return ""
        try:
            import markdownify

            # Only run markdownify if the content looks like HTML
            if "<" in content and ">" in content:
                return markdownify.markdownify(
                    content, heading_style="ATX", strip=["img", "a"]
                )
            return content
        except Exception as exc:
            logger.debug("markdownify conversion failed: %s", exc)
            return content

    @staticmethod
    def _normalize_whitespace(text: str) -> str:
        # Collapse 3+ consecutive blank lines to 2
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Strip trailing whitespace per line
        lines = [line.rstrip() for line in text.split("\n")]
        return "\n".join(lines).strip()

    @staticmethod
    def _count_tokens(text: str) -> int:
        try:
            import tiktoken

            enc = tiktoken.get_encoding(_TIKTOKEN_ENCODING)
            return len(enc.encode(text))
        except Exception:
            # Fallback approximation: ~4 chars per token
            return max(1, len(text) // 4)

    @staticmethod
    def _truncate_to_tokens(text: str, max_tokens: int) -> str:
        try:
            import tiktoken

            enc = tiktoken.get_encoding(_TIKTOKEN_ENCODING)
            tokens = enc.encode(text)[:max_tokens]
            return enc.decode(tokens)
        except Exception:
            # Fallback: truncate by character count
            return text[: max_tokens * 4]
