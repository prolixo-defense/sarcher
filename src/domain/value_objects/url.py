import re
from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse, urlencode, parse_qs


_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "msclkid", "ref", "source", "mc_cid", "mc_eid",
})


@dataclass(frozen=True)
class URL:
    value: str

    def __post_init__(self) -> None:
        normalized = self._normalize(self.value)
        if not normalized:
            raise ValueError(f"Invalid URL: {self.value!r}")
        object.__setattr__(self, "value", normalized)

    def _normalize(self, raw: str) -> str:
        raw = raw.strip()
        # Add scheme if missing
        if raw and not re.match(r"^https?://", raw, re.IGNORECASE):
            raw = "https://" + raw
        parsed = urlparse(raw)
        if not parsed.netloc:
            raise ValueError(f"Invalid URL: {raw!r}")
        # Strip tracking params
        params = {k: v for k, v in parse_qs(parsed.query).items()
                  if k.lower() not in _TRACKING_PARAMS}
        clean_query = urlencode(params, doseq=True)
        normalized = urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/") or "/",
            parsed.params,
            clean_query,
            "",  # strip fragment
        ))
        return normalized

    @property
    def domain(self) -> str:
        return urlparse(self.value).netloc

    def __str__(self) -> str:
        return self.value
