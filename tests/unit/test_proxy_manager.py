"""Tests for ProxyManager — rotation, failure reporting, cooldown logic."""
import os
import time
import tempfile
import pytest

from src.infrastructure.proxy.proxy_manager import ProxyManager, COOLDOWN_SECONDS


@pytest.fixture
def proxy_file(tmp_path):
    """Create a temp proxy file with a few entries."""
    p = tmp_path / "proxies.txt"
    p.write_text(
        "http://proxy1.example.com:8080\n"
        "http://proxy2.example.com:8080\n"
        "http://proxy3.example.com:8080\n"
        "# this is a comment\n"
        "\n"  # blank line should be ignored
    )
    return str(p)


@pytest.mark.asyncio
async def test_get_proxy_no_file_returns_none():
    mgr = ProxyManager(proxy_file="/nonexistent/proxies.txt")
    result = await mgr.get_proxy()
    assert result is None


@pytest.mark.asyncio
async def test_get_proxy_with_file_returns_proxy(proxy_file):
    mgr = ProxyManager(proxy_file=proxy_file)
    result = await mgr.get_proxy()
    assert result is not None
    assert result.startswith("http://proxy")


@pytest.mark.asyncio
async def test_get_proxy_round_robin(proxy_file):
    mgr = ProxyManager(proxy_file=proxy_file)
    results = [await mgr.get_proxy() for _ in range(6)]
    # Should cycle through all 3 proxies twice
    assert len(set(results)) == 3


@pytest.mark.asyncio
async def test_report_failure_triggers_cooldown(proxy_file):
    mgr = ProxyManager(proxy_file=proxy_file)
    proxy = "http://proxy1.example.com:8080"

    # Force load so the proxy is in the list
    mgr._load()
    assert not mgr._is_cooling(proxy)

    await mgr.report_failure(proxy, "403")
    assert mgr._is_cooling(proxy)


@pytest.mark.asyncio
async def test_cooling_proxy_excluded_from_rotation(proxy_file):
    mgr = ProxyManager(proxy_file=proxy_file)
    mgr._load()
    proxy1 = "http://proxy1.example.com:8080"
    await mgr.report_failure(proxy1, "403")

    # Rotate many times — proxy1 should never appear
    results = [await mgr.get_proxy() for _ in range(20)]
    assert proxy1 not in results


@pytest.mark.asyncio
async def test_all_proxies_cooling_returns_none(proxy_file):
    mgr = ProxyManager(proxy_file=proxy_file)
    mgr._load()
    for proxy in list(mgr._proxies):
        await mgr.report_failure(proxy, "banned")

    result = await mgr.get_proxy()
    assert result is None


@pytest.mark.asyncio
async def test_sticky_session_per_domain(proxy_file):
    mgr = ProxyManager(proxy_file=proxy_file)
    first = await mgr.get_proxy(domain="example.com")
    second = await mgr.get_proxy(domain="example.com")
    assert first == second, "Same domain should receive the same proxy (sticky)"


@pytest.mark.asyncio
async def test_different_domains_may_get_different_proxies(proxy_file):
    mgr = ProxyManager(proxy_file=proxy_file)
    results = set()
    for i in range(10):
        r = await mgr.get_proxy(domain=f"domain{i}.com")
        if r:
            results.add(r)
    # With 3 proxies and 10 different domains we should see multiple proxies
    assert len(results) > 1
