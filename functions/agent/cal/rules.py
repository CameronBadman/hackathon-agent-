import re
from typing import Any, Dict, List, Tuple

from .config import (
    INDIA_GEO_KEYWORDS,
    IN_PERSON_OR_HYBRID_KEYWORDS,
    ONLINE_STRONG_KEYWORDS,
    ONLINE_WEAK_KEYWORDS,
)


def contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    lowered = (text or "").lower()
    return any(pattern in lowered for pattern in patterns)


def _extract_location_lines(skills_text: str) -> List[str]:
    lines = skills_text.splitlines()
    in_locations = False
    extracted: List[str] = []
    for raw in lines:
        line = raw.strip()
        if line.startswith("## "):
            in_locations = line.lower() == "## locations"
            continue
        if not in_locations:
            continue
        if line.startswith("- "):
            cleaned = re.sub(r"\([^)]*\)", "", line[2:]).strip().lower()
            if cleaned:
                extracted.append(cleaned)
    return extracted


def build_location_policy(skills_text: str) -> Dict[str, Any]:
    lines = _extract_location_lines(skills_text)
    explicit_locations: List[str] = []
    allow_fully_online = False
    for loc in lines:
        if "online" in loc or "remote" in loc or "virtual" in loc:
            allow_fully_online = True
            continue
        explicit_locations.append(loc)
    return {
        "explicit_locations": explicit_locations,
        "allow_fully_online": allow_fully_online,
    }


def location_gate(hackathon: Dict[str, Any], page_text: str, location_policy: Dict[str, Any]) -> Tuple[bool, str]:
    url = str(hackathon.get("url", "")).lower()
    event_text = " ".join(
        [
            str(hackathon.get("location", "")),
            str(hackathon.get("description", "")),
            str(hackathon.get("evidence", "")),
            str(hackathon.get("location_evidence", "")),
            page_text or "",
        ]
    ).lower()

    india_text = f" {event_text} "
    if contains_any(india_text, INDIA_GEO_KEYWORDS) or ".in/" in url or url.endswith(".in"):
        return False, "Rejected: India-based event excluded by location policy"

    explicit_locations = [x.lower() for x in location_policy.get("explicit_locations", [])]
    allow_fully_online = bool(location_policy.get("allow_fully_online", False))
    has_explicit_location_match = any(loc in event_text for loc in explicit_locations)
    has_online_strong = contains_any(event_text, ONLINE_STRONG_KEYWORDS)
    has_online_weak = contains_any(event_text, ONLINE_WEAK_KEYWORDS)
    has_in_person_or_hybrid = contains_any(event_text, IN_PERSON_OR_HYBRID_KEYWORDS)

    if has_explicit_location_match:
        return True, "Accepted: matches explicit in-person location policy from SKILLS.md"
    if allow_fully_online and has_online_strong and not has_in_person_or_hybrid:
        return True, "Accepted: fully-online event confirmed from listing/page text"
    if has_online_weak and has_in_person_or_hybrid:
        return False, "Rejected: event appears hybrid or in-person despite online wording; must be fully online or Brisbane-based"
    if allow_fully_online and has_online_weak and not has_online_strong:
        return False, "Rejected: online wording is ambiguous; requires explicit fully-online or Brisbane-based evidence"
    return False, "Rejected: does not match SKILLS.md location policy (explicit location or fully-online)"
