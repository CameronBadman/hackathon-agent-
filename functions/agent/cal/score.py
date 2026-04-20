from typing import Any, Dict

from .common import domain_from_url
from .config import SUSPICIOUS_TITLE_PREFIXES, TRUSTED_SOURCE_DOMAINS


def as_unit_float(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, parsed))


def looks_trusted_source(url: str) -> bool:
    host = domain_from_url(url)
    if not host:
        return False
    return any(host == d or host.endswith(f".{d}") for d in TRUSTED_SOURCE_DOMAINS)


def looks_suspicious_title(name: str) -> bool:
    lowered = (name or "").strip().lower()
    return any(lowered.startswith(prefix) for prefix in SUSPICIOUS_TITLE_PREFIXES)


def quality_score(candidate: Dict[str, Any], validation: Dict[str, Any]) -> float:
    url = (candidate.get("url") or "").strip()
    name = (candidate.get("name") or "").strip()

    score = 0.0
    score += 0.30 if looks_trusted_source(url) else 0.05
    score += 0.25 * as_unit_float(validation.get("confidence"))
    score += 0.25 if bool(validation.get("is_genuine", False)) else -0.20
    # Discovery-stage `matches_skills` can be noisy; location and final filters decide suitability.
    score += 0.15 if bool(validation.get("matches_skills", False)) else 0.0
    if looks_suspicious_title(name):
        score -= 0.35
    if any(t in url.lower() for t in ("/event/", "/events/", "/hackathon", "/hackathons")):
        score += 0.05
    return max(0.0, min(1.0, score))
