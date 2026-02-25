"""
Human-like scroll behaviour simulation.

Scrolls in variable-sized chunks with randomised delays, occasional
reading pauses, and rare overscroll-and-correct events.
"""
import asyncio
import random
from typing import Optional


async def human_scroll(
    page,
    direction: str = "down",
    amount: Optional[int] = None,
):
    """
    Scroll a Playwright page in a human-like pattern.

    Parameters
    ----------
    page:      Playwright page object.
    direction: "down" or "up".
    amount:    Total pixels to scroll. Randomised (300–1200) if not given.
    """
    total = amount if amount is not None else random.randint(300, 1200)
    sign = 1 if direction == "down" else -1
    scrolled = 0

    while scrolled < total:
        # Variable chunk per event (80–300 px)
        chunk = min(random.randint(80, 300), total - scrolled)
        await page.mouse.wheel(0, sign * chunk)
        scrolled += chunk

        # Inter-event delay: 200–800 ms
        await asyncio.sleep(random.uniform(0.2, 0.8))

        # Simulate pausing to read (10 % chance)
        if random.random() < 0.10:
            await asyncio.sleep(random.uniform(1.0, 3.5))

        # Occasional slight overshoot + correction (5 % chance, only after > 100 px)
        if scrolled > 100 and random.random() < 0.05:
            overshoot = random.randint(20, 80)
            await page.mouse.wheel(0, -sign * overshoot)
            await asyncio.sleep(random.uniform(0.1, 0.4))
