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


def _location_aliases(location_line: str) -> List[str]:
    location = re.sub(r"\s+", " ", (location_line or "").strip().lower())
    if not location:
        return []
    aliases = {location}
    parts = [p.strip() for p in location.split(",") if p.strip()]
    if parts:
        aliases.add(parts[0])
        if len(parts) >= 2:
            aliases.add(f"{parts[0]}, {parts[1]}")
            aliases.add(f"{parts[0]} {parts[1]}")
    return [a for a in aliases if len(a) >= 3]


def _contains_alias(text: str, alias: str) -> bool:
    escaped = re.escape((alias or "").strip().lower())
    if not escaped:
        return False
    return re.search(rf"(^|[^a-z0-9]){escaped}([^a-z0-9]|$)", text.lower()) is not None


def build_location_policy(skills_text: str) -> Dict[str, Any]:
    lines = _extract_location_lines(skills_text)
    explicit_locations: List[str] = []
    location_aliases: List[str] = []
    allow_fully_online = False
    for loc in lines:
        if "online" in loc or "remote" in loc or "virtual" in loc:
            allow_fully_online = True
            continue
        explicit_locations.append(loc)
        location_aliases.extend(_location_aliases(loc))
    return {
        "explicit_locations": explicit_locations,
        "location_aliases": sorted(set(location_aliases), key=len, reverse=True),
        "allow_fully_online": allow_fully_online,
    }


def location_gate(hackathon: Dict[str, Any], page_text: str, location_policy: Dict[str, Any]) -> Tuple[bool, str]:
    url = str(hackathon.get("url", "")).lower()
    structured_text = " ".join(
        [
            str(hackathon.get("name", "")),
            str(hackathon.get("location", "")),
            str(hackathon.get("description", "")),
            str(hackathon.get("evidence", "")),
            str(hackathon.get("location_evidence", "")),
            str(hackathon.get("event_mode", "")),
        ]
    ).lower()
    page_text = (page_text or "").lower()
    event_text = f"{structured_text} {page_text}".strip()

    india_text = f" {event_text} "
    if contains_any(india_text, INDIA_GEO_KEYWORDS) or ".in/" in url or url.endswith(".in"):
        return False, "Rejected: India-based event excluded by location policy"

    explicit_locations = [x.lower() for x in location_policy.get("explicit_locations", [])]
    location_aliases = [x.lower() for x in location_policy.get("location_aliases", [])]
    allow_fully_online = bool(location_policy.get("allow_fully_online", False))
    has_explicit_location_match = any(loc in event_text for loc in explicit_locations) or any(
        _contains_alias(event_text, alias) for alias in location_aliases
    )
    location_mode_text = " ".join(
        [
            str(hackathon.get("location", "")),
            str(hackathon.get("event_mode", "")),
            str(hackathon.get("location_evidence", "")),
        ]
    ).lower()
    has_online_label = contains_any(location_mode_text, ONLINE_WEAK_KEYWORDS) or "fully_online" in location_mode_text
    has_online_strong_structured = contains_any(structured_text, ONLINE_STRONG_KEYWORDS) or "fully_online" in structured_text
    has_online_strong_page = contains_any(page_text, ONLINE_STRONG_KEYWORDS)
    has_online_weak_structured = contains_any(structured_text, ONLINE_WEAK_KEYWORDS)
    has_online_weak_page = contains_any(page_text, ONLINE_WEAK_KEYWORDS)
    has_in_person_or_hybrid = contains_any(event_text, IN_PERSON_OR_HYBRID_KEYWORDS)

    negated_location = False
    for alias in location_aliases:
        for marker in ("not in", "outside", "not based in", "except"):
            if f"{marker} {alias}" in event_text:
                negated_location = True
                break
        if negated_location:
            break

    if has_explicit_location_match and not negated_location:
        return True, "Accepted: matches explicit in-person location policy from SKILLS.md"
    if allow_fully_online and not has_in_person_or_hybrid:
        if has_online_strong_page or has_online_strong_structured:
            return True, "Accepted: fully-online event confirmed from event fields or page text"
        if has_online_label and (has_online_weak_structured or has_online_weak_page):
            return True, "Accepted: online event with consistent evidence across listing and page"
    if (has_online_weak_structured or has_online_weak_page) and has_in_person_or_hybrid:
        return False, "Rejected: event appears hybrid or in-person despite online wording; must be fully online or Brisbane-based"
    if allow_fully_online and (has_online_weak_structured or has_online_weak_page):
        return False, "Rejected: online wording is too ambiguous to confirm fully-online eligibility"
    return False, "Rejected: does not match SKILLS.md location policy (explicit location or fully-online)"
