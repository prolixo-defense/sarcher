import random
from typing import Optional

try:
    from curl_cffi.requests import AsyncSession  # noqa: F401
    CURL_CFFI_AVAILABLE = True
except ImportError:
    CURL_CFFI_AVAILABLE = False

# Ordered list of impersonation profiles for round-robin rotation
IMPERSONATION_PROFILES = [
    "chrome120", "chrome119", "chrome116",
    "chrome110", "chrome107", "chrome104",
    "edge101", "edge99",
    "safari17_0", "safari15_5",
]

# Matching User-Agent strings — MUST align with the TLS profile.
# Chrome TLS fingerprint must pair with a Chrome UA, Safari with Safari UA, etc.
PROFILE_USER_AGENTS: dict[str, str] = {
    "chrome120": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "chrome119": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
    ),
    "chrome116": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36"
    ),
    "chrome110": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
    ),
    "chrome107": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.0.0 Safari/537.36"
    ),
    "chrome104": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.0.0 Safari/537.36"
    ),
    "edge101": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.64 Safari/537.36 Edg/101.0.1210.53"
    ),
    "edge99": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.51 Safari/537.36 Edg/99.0.1150.30"
    ),
    "safari17_0": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
    ),
    "safari15_5": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 12_5) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.5 Safari/605.1.15"
    ),
}


class TLSManager:
    """Manages curl_cffi browser impersonation profiles for TLS fingerprint spoofing."""

    def __init__(self, rotate_randomly: bool = False):
        self._profiles = list(IMPERSONATION_PROFILES)
        self._index = 0
        self._rotate_randomly = rotate_randomly

    def get_profile(self) -> str:
        """Return the next impersonation profile (round-robin or random)."""
        if self._rotate_randomly:
            return random.choice(self._profiles)
        profile = self._profiles[self._index % len(self._profiles)]
        self._index += 1
        return profile

    def get_user_agent(self, profile: str) -> str:
        """Return the matching User-Agent string for a given profile."""
        return PROFILE_USER_AGENTS.get(profile, PROFILE_USER_AGENTS["chrome120"])

    def get_profile_and_ua(self) -> tuple[str, str]:
        """Return (profile, user_agent) together — always a consistent pair."""
        profile = self.get_profile()
        return profile, self.get_user_agent(profile)

    def get_session(self, profile: Optional[str] = None):
        """Return a configured curl_cffi AsyncSession with the chosen impersonation profile."""
        if not CURL_CFFI_AVAILABLE:
            raise ImportError("curl_cffi is not installed. Run: pip install curl-cffi")
        from curl_cffi.requests import AsyncSession
        if profile is None:
            profile = self.get_profile()
        return AsyncSession(impersonate=profile)
