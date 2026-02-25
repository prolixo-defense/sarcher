"""
Lightweight DAG execution engine.

A DAG is defined as a dict of steps with dependencies:
{
    "scrape": {"func": some_func, "depends_on": [], "retry": 2},
    "extract": {"func": other_func, "depends_on": ["scrape"]},
    "enrich": {"func": enrich_func, "depends_on": ["extract"]},
}

Features:
- Respects dependencies (topological execution order)
- Parallel execution of independent steps
- Configurable retry on failure
- State persistence via results dict
"""
import asyncio
import logging
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)


class DAGRunner:
    """Lightweight async DAG execution engine."""

    def __init__(self):
        self._results: dict[str, Any] = {}

    async def run(self, dag: dict, context: dict | None = None) -> dict:
        """
        Execute a DAG in dependency order.

        dag format:
        {
            "step_name": {
                "func": callable,       # async or sync callable
                "depends_on": list[str],
                "retry": int,           # optional, default 1
                "description": str,     # optional
            }
        }

        Returns {step_name: {status, result, duration_s, error}}.
        """
        if context is None:
            context = {}

        results: dict[str, dict] = {}
        execution_order = self._topological_sort(dag)

        logger.info("[DAGRunner] Executing %d-step DAG: %s", len(dag), execution_order)

        # Group steps that can run in parallel
        completed = set()
        while len(completed) < len(dag):
            # Find steps ready to run (all deps completed successfully)
            ready = [
                step_name
                for step_name in execution_order
                if step_name not in completed
                and all(
                    dep in completed and results.get(dep, {}).get("status") == "success"
                    for dep in dag[step_name].get("depends_on", [])
                )
            ]
            if not ready:
                # Check if any remaining steps have failed deps
                remaining = set(execution_order) - completed
                for step_name in remaining:
                    if step_name not in results:
                        failed_deps = [
                            dep
                            for dep in dag[step_name].get("depends_on", [])
                            if results.get(dep, {}).get("status") != "success"
                        ]
                        if failed_deps:
                            results[step_name] = {
                                "status": "skipped",
                                "result": None,
                                "duration_s": 0,
                                "error": f"Dependency failed: {failed_deps}",
                            }
                            completed.add(step_name)
                if not (set(execution_order) - completed):
                    break
                await asyncio.sleep(0.01)
                continue

            # Run ready steps in parallel
            tasks = [self._run_step(step_name, dag[step_name], context, results) for step_name in ready]
            step_results = await asyncio.gather(*tasks, return_exceptions=False)
            for step_name, step_result in zip(ready, step_results):
                results[step_name] = step_result
                completed.add(step_name)

        return results

    async def _run_step(
        self, step_name: str, step_config: dict, context: dict, results: dict
    ) -> dict:
        """Execute a single step with retry logic."""
        func = step_config["func"]
        max_retries = step_config.get("retry", 1)
        description = step_config.get("description", step_name)

        last_error = None
        for attempt in range(1, max_retries + 1):
            start = time.monotonic()
            try:
                logger.info("[DAGRunner] Running '%s' (attempt %d/%d)", step_name, attempt, max_retries)
                if asyncio.iscoroutinefunction(func):
                    result = await func(context=context, results=results)
                else:
                    result = func(context=context, results=results)
                duration = time.monotonic() - start
                logger.info("[DAGRunner] '%s' succeeded in %.2fs", step_name, duration)
                return {
                    "status": "success",
                    "result": result,
                    "duration_s": round(duration, 3),
                    "error": None,
                }
            except Exception as exc:
                duration = time.monotonic() - start
                last_error = exc
                logger.warning(
                    "[DAGRunner] '%s' failed (attempt %d/%d) in %.2fs: %s",
                    step_name, attempt, max_retries, duration, exc,
                )
                if attempt < max_retries:
                    await asyncio.sleep(2 ** attempt)

        return {
            "status": "failed",
            "result": None,
            "duration_s": 0,
            "error": str(last_error),
        }

    def _topological_sort(self, dag: dict) -> list[str]:
        """Kahn's algorithm for topological sort."""
        in_degree = {node: 0 for node in dag}
        adjacency: dict[str, list[str]] = {node: [] for node in dag}

        for node, config in dag.items():
            for dep in config.get("depends_on", []):
                if dep in dag:
                    adjacency[dep].append(node)
                    in_degree[node] += 1

        queue = [node for node, deg in in_degree.items() if deg == 0]
        result = []

        while queue:
            node = queue.pop(0)
            result.append(node)
            for neighbor in adjacency[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(result) != len(dag):
            raise ValueError("DAG has a cycle — cannot determine execution order")

        return result
