"""
Semi-Markov typing simulator.

Types text with human-like timing:
- WPM-based base delay with per-character variance
- Common English bigrams typed faster (muscle memory)
- ~3% typo rate using QWERTY neighbour keys, corrected with Backspace
- Gradual fatigue: ~2% slowdown per 50 characters typed
"""
import asyncio
import random
from typing import Optional

# High-frequency English bigrams — typed faster due to muscle memory
FAST_BIGRAMS: set[str] = {
    "th", "he", "in", "er", "an", "re", "on", "en", "at", "es",
    "ed", "nd", "to", "or", "ea", "ti", "ar", "te", "ng", "al",
    "it", "as", "is", "ha", "et", "se", "ou", "of", "nt", "hi",
}

# QWERTY neighbour keys for realistic typo generation
QWERTY_NEIGHBORS: dict[str, str] = {
    "a": "sqwz", "b": "vghn", "c": "xdfv", "d": "serfcx", "e": "wsdr",
    "f": "drtgvc", "g": "ftyhbv", "h": "gyujnb", "i": "uojk", "j": "huikm",
    "k": "jiolm", "l": "kop", "m": "njk", "n": "bhjm", "o": "iklp",
    "p": "ol", "q": "wa", "r": "edft", "s": "awedxz", "t": "rfgy",
    "u": "yhji", "v": "cfgb", "w": "qase", "x": "zsdc", "y": "tghu",
    "z": "asx",
}


def _wpm_to_char_delay(wpm: float) -> float:
    """Convert words-per-minute to per-character delay in seconds (5 chars/word)."""
    chars_per_minute = wpm * 5.0
    return 60.0 / chars_per_minute


def _neighbour_key(char: str) -> Optional[str]:
    """Return a random QWERTY neighbour of the given character, or None."""
    neighbours = QWERTY_NEIGHBORS.get(char.lower(), "")
    return random.choice(neighbours) if neighbours else None


async def human_type(page, selector: str, text: str, wpm: float = 65.0):
    """
    Click *selector* then type *text* with human-like timing.

    Parameters
    ----------
    page:     Playwright page object.
    selector: CSS selector for the input field.
    text:     Text to type.
    wpm:      Target typing speed (words per minute). Default 65 ≈ average typist.
    """
    await page.click(selector)
    await asyncio.sleep(random.uniform(0.1, 0.3))  # focus settle

    base_delay = _wpm_to_char_delay(wpm)
    i = 0
    while i < len(text):
        char = text[i]

        # Fatigue: +2% slowdown every 50 characters
        fatigue = 1.0 + (i // 50) * 0.02
        delay = base_delay * fatigue

        # Bigram acceleration
        if i > 0:
            bigram = text[i - 1 : i + 1].lower()
            if bigram in FAST_BIGRAMS:
                delay *= 0.65

        # ±30% random variance
        delay *= random.uniform(0.70, 1.30)

        # Occasional typo (~3% for alphabetic characters)
        if char.isalpha() and random.random() < 0.03:
            typo = _neighbour_key(char)
            if typo:
                await page.keyboard.type(typo)
                await asyncio.sleep(delay * random.uniform(0.8, 1.2))
                # Notice and correct the mistake
                await asyncio.sleep(random.uniform(0.08, 0.25))
                await page.keyboard.press("Backspace")
                await asyncio.sleep(random.uniform(0.05, 0.15))

        await page.keyboard.type(char)
        await asyncio.sleep(max(delay, 0.01))
        i += 1
