"""Tests for TLSManager — profile rotation and UA consistency."""
import pytest
from src.infrastructure.fingerprint.tls_manager import (
    TLSManager,
    IMPERSONATION_PROFILES,
    PROFILE_USER_AGENTS,
)


def test_all_profiles_have_matching_ua():
    """Every impersonation profile must have a matching User-Agent."""
    for profile in IMPERSONATION_PROFILES:
        ua = PROFILE_USER_AGENTS.get(profile)
        assert ua, f"Profile '{profile}' has no matching User-Agent"
        assert len(ua) > 20, f"UA for '{profile}' looks too short: {ua!r}"


def test_chrome_profiles_have_chrome_ua():
    """Chrome TLS profiles must pair with Chrome User-Agents."""
    for profile in IMPERSONATION_PROFILES:
        if profile.startswith("chrome"):
            ua = PROFILE_USER_AGENTS[profile]
            assert "Chrome/" in ua, f"Chrome profile '{profile}' has non-Chrome UA: {ua!r}"


def test_safari_profiles_have_safari_ua():
    """Safari TLS profiles must pair with Safari User-Agents."""
    for profile in IMPERSONATION_PROFILES:
        if profile.startswith("safari"):
            ua = PROFILE_USER_AGENTS[profile]
            assert "Safari/" in ua, f"Safari profile '{profile}' has non-Safari UA: {ua!r}"
            assert "Chrome/" not in ua, f"Safari profile '{profile}' should not have Chrome UA"


def test_round_robin_rotation():
    """Profiles should cycle in order, not repeat until all exhausted."""
    mgr = TLSManager(rotate_randomly=False)
    seen = [mgr.get_profile() for _ in range(len(IMPERSONATION_PROFILES))]
    assert len(set(seen)) == len(IMPERSONATION_PROFILES), "Expected each profile once in one cycle"


def test_round_robin_wraps_around():
    """After all profiles are used, rotation wraps back to the first."""
    mgr = TLSManager(rotate_randomly=False)
    n = len(IMPERSONATION_PROFILES)
    first = mgr.get_profile()
    for _ in range(n - 1):
        mgr.get_profile()
    # Next call should return the same as the first
    assert mgr.get_profile() == first


def test_random_rotation_stays_valid():
    """Random rotation should always return a known profile."""
    mgr = TLSManager(rotate_randomly=True)
    for _ in range(50):
        profile = mgr.get_profile()
        assert profile in IMPERSONATION_PROFILES


def test_get_profile_and_ua_consistent():
    """get_profile_and_ua() should return a matched pair."""
    mgr = TLSManager()
    for _ in range(len(IMPERSONATION_PROFILES)):
        profile, ua = mgr.get_profile_and_ua()
        expected_ua = PROFILE_USER_AGENTS[profile]
        assert ua == expected_ua, f"UA mismatch for profile {profile}"


def test_get_user_agent_unknown_profile_falls_back():
    """Unknown profile names should fall back to the chrome120 UA."""
    mgr = TLSManager()
    ua = mgr.get_user_agent("totally_unknown_browser99")
    assert "Chrome/120" in ua
