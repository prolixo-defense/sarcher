"""
Bezier-curve mouse movement simulation for human-like browser interactions.

Generates smooth, natural-looking mouse paths from point A to point B using
cubic Bezier curves, Gaussian micro-jitter, and sinusoidal speed variation.
"""
import asyncio
import math
import random
from typing import Tuple


def _bezier_point(
    t: float,
    p0: Tuple[float, float],
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    p3: Tuple[float, float],
) -> Tuple[float, float]:
    """Evaluate a cubic Bezier curve at parameter t ∈ [0, 1]."""
    x = (
        (1 - t) ** 3 * p0[0]
        + 3 * (1 - t) ** 2 * t * p1[0]
        + 3 * (1 - t) * t ** 2 * p2[0]
        + t ** 3 * p3[0]
    )
    y = (
        (1 - t) ** 3 * p0[1]
        + 3 * (1 - t) ** 2 * t * p1[1]
        + 3 * (1 - t) * t ** 2 * p2[1]
        + t ** 3 * p3[1]
    )
    return (x, y)


def generate_bezier_path(
    start: Tuple[float, float],
    end: Tuple[float, float],
    num_points: int = 75,
) -> list[Tuple[float, float]]:
    """
    Generate a list of (x, y) waypoints along a randomized Bezier curve.

    Control points are offset randomly from the straight line to produce
    organic-looking curves. Gaussian noise is added to each point to simulate
    the micro-tremor of a human hand.
    """
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    spread_x = max(abs(dx) * 0.3, 30)
    spread_y = max(abs(dy) * 0.3, 30)

    cp1 = (
        start[0] + dx * 0.3 + random.uniform(-spread_x, spread_x),
        start[1] + dy * 0.3 + random.uniform(-spread_y, spread_y),
    )
    cp2 = (
        start[0] + dx * 0.7 + random.uniform(-spread_x, spread_x),
        start[1] + dy * 0.7 + random.uniform(-spread_y, spread_y),
    )

    path: list[Tuple[float, float]] = []
    for i in range(num_points):
        t = i / max(num_points - 1, 1)
        pt = _bezier_point(t, start, cp1, cp2, end)
        # Gaussian micro-jitter (σ ≈ 1.5 px)
        noise_x = random.gauss(0, 1.5)
        noise_y = random.gauss(0, 1.5)
        path.append((pt[0] + noise_x, pt[1] + noise_y))

    return path


async def human_move_mouse(
    page,
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
):
    """
    Move the Playwright mouse from (start_x, start_y) to (end_x, end_y)
    along a Bezier curve with sinusoidal speed variation (faster in the
    middle of the stroke, slower at the edges).
    """
    num_points = random.randint(50, 100)
    path = generate_bezier_path((start_x, start_y), (end_x, end_y), num_points)

    for i, (x, y) in enumerate(path):
        t = i / max(len(path) - 1, 1)
        # sin(t·π) peaks at 0.5 → fastest in middle, slowest at edges
        speed_factor = math.sin(t * math.pi)
        base_delay = random.uniform(0.005, 0.015)
        delay = base_delay * (1.0 - speed_factor * 0.7)
        await page.mouse.move(x, y)
        await asyncio.sleep(delay)


async def human_click(page, selector: str):
    """
    Click an element with a human-like mouse trajectory:

    1. Locate the element's bounding box
    2. Pick a random point inside it (not dead-centre)
    3. Approach from a random offset using human_move_mouse
    4. Pause briefly, then press/release with a randomised hold duration
    """
    element = await page.query_selector(selector)
    if element is None:
        return

    box = await element.bounding_box()
    if box is None:
        return

    # Target a random interior point of the element
    target_x = box["x"] + random.uniform(box["width"] * 0.2, box["width"] * 0.8)
    target_y = box["y"] + random.uniform(box["height"] * 0.2, box["height"] * 0.8)

    # Start from a plausible nearby position
    start_x = max(0.0, target_x + random.uniform(-250, 250))
    start_y = max(0.0, target_y + random.uniform(-180, 180))

    await human_move_mouse(page, start_x, start_y, target_x, target_y)

    # Pre-click pause (50–150 ms)
    await asyncio.sleep(random.uniform(0.05, 0.15))

    # Click with randomised hold duration (50–100 ms)
    await page.mouse.down()
    await asyncio.sleep(random.uniform(0.05, 0.10))
    await page.mouse.up()
