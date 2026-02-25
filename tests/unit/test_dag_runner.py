"""
Tests for DAGRunner — topological execution and dependency handling.

No mocks needed — uses simple test functions as DAG steps.
"""
import asyncio
import pytest

from src.infrastructure.orchestration.dag_runner import DAGRunner


async def _success_func(context, results):
    return {"ok": True}


async def _fail_func(context, results):
    raise ValueError("Step failed!")


async def _uses_result_func(context, results):
    prev = results.get("step_a", {}).get("result", {})
    return {"used": prev.get("ok", False)}


# ---------------------------------------------------------------------------
# Basic execution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_step_runs_successfully():
    runner = DAGRunner()
    dag = {"step_a": {"func": _success_func, "depends_on": []}}
    results = await runner.run(dag)
    assert results["step_a"]["status"] == "success"
    assert results["step_a"]["result"]["ok"] is True


@pytest.mark.asyncio
async def test_two_step_dag_runs_in_order():
    execution_order = []

    async def first(context, results):
        execution_order.append("first")
        return {}

    async def second(context, results):
        execution_order.append("second")
        return {}

    runner = DAGRunner()
    dag = {
        "first": {"func": first, "depends_on": []},
        "second": {"func": second, "depends_on": ["first"]},
    }
    await runner.run(dag)
    assert execution_order == ["first", "second"]


@pytest.mark.asyncio
async def test_step_has_access_to_previous_result():
    runner = DAGRunner()
    dag = {
        "step_a": {"func": _success_func, "depends_on": []},
        "step_b": {"func": _uses_result_func, "depends_on": ["step_a"]},
    }
    results = await runner.run(dag)
    assert results["step_b"]["status"] == "success"
    assert results["step_b"]["result"]["used"] is True


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_step_marks_dependents_as_skipped():
    runner = DAGRunner()
    dag = {
        "step_a": {"func": _fail_func, "depends_on": [], "retry": 1},
        "step_b": {"func": _success_func, "depends_on": ["step_a"]},
    }
    results = await runner.run(dag)
    assert results["step_a"]["status"] == "failed"
    assert results["step_b"]["status"] == "skipped"


@pytest.mark.asyncio
async def test_independent_steps_both_run_despite_one_failing():
    runner = DAGRunner()
    dag = {
        "step_a": {"func": _fail_func, "depends_on": [], "retry": 1},
        "step_b": {"func": _success_func, "depends_on": []},  # independent
    }
    results = await runner.run(dag)
    assert results["step_a"]["status"] == "failed"
    assert results["step_b"]["status"] == "success"


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_succeeds_on_second_attempt():
    call_count = [0]

    async def flaky(context, results):
        call_count[0] += 1
        if call_count[0] < 2:
            raise Exception("Transient error")
        return {"calls": call_count[0]}

    runner = DAGRunner()
    dag = {"step_a": {"func": flaky, "depends_on": [], "retry": 3}}
    results = await runner.run(dag)
    assert results["step_a"]["status"] == "success"
    assert call_count[0] == 2


# ---------------------------------------------------------------------------
# Topological sort
# ---------------------------------------------------------------------------


def test_topological_sort_simple_chain():
    runner = DAGRunner()
    dag = {
        "a": {"func": _success_func, "depends_on": []},
        "b": {"func": _success_func, "depends_on": ["a"]},
        "c": {"func": _success_func, "depends_on": ["b"]},
    }
    order = runner._topological_sort(dag)
    assert order.index("a") < order.index("b") < order.index("c")


def test_topological_sort_raises_on_cycle():
    runner = DAGRunner()
    dag = {
        "a": {"func": _success_func, "depends_on": ["b"]},
        "b": {"func": _success_func, "depends_on": ["a"]},
    }
    with pytest.raises(ValueError, match="cycle"):
        runner._topological_sort(dag)


@pytest.mark.asyncio
async def test_context_is_passed_to_all_steps():
    received_contexts = []

    async def capture_context(context, results):
        received_contexts.append(context.get("test_key"))
        return {}

    runner = DAGRunner()
    dag = {"step_a": {"func": capture_context, "depends_on": []}}
    await runner.run(dag, context={"test_key": "hello"})
    assert received_contexts == ["hello"]
