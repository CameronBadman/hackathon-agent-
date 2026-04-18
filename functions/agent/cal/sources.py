import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests

from .common import normalize_url, to_iso_date
from .config import CONFIG, DEVPOST_API_URL, SOURCE_HINTS
from .evidence import extract_ldjson_event
from .llm import call_gemini_json

LOGGER = logging.getLogger(__name__)


def _parse_submission_period_dates(raw: str) -> Tuple[Optional[str], Optional[str]]:
    text = (raw or "").strip()
    if not text:
        return None, None

    # Typical Devpost shape: "Jan 10 - Apr 20, 2026"
    m = re.search(
        r"([A-Za-z]{3,9}\s+\d{1,2})(?:,\s*(\d{4}))?\s*[-–]\s*([A-Za-z]{3,9}\s+\d{1,2})(?:,\s*(\d{4}))?",
        text,
    )
    if not m:
        return None, None

    left_date = m.group(1)
    left_year = m.group(2)
    right_date = m.group(3)
    right_year = m.group(4)
    if right_year and not left_year:
        left_year = right_year
    if left_year and not right_year:
        right_year = left_year

    if not left_year or not right_year:
        return None, None

    def _parse_piece(date_part: str, year_part: str) -> Optional[str]:
        for fmt in ("%b %d %Y", "%B %d %Y"):
            try:
                return datetime.strptime(f"{date_part} {year_part}", fmt).date().isoformat()
            except ValueError:
                continue
        return None

    return _parse_piece(left_date, left_year), _parse_piece(right_date, right_year)


def _resolve_devpost_dates(item: Dict[str, Any], ld: Dict[str, Any]) -> Tuple[str, str]:
    start_date = to_iso_date(str(ld.get("startDate", ""))) or ""
    end_date = to_iso_date(str(ld.get("endDate", ""))) or ""
    if start_date and end_date:
        return start_date, end_date

    for field in ("start_time", "starts_at", "start_date"):
        if not start_date:
            start_date = to_iso_date(str(item.get(field, ""))) or start_date
    for field in ("end_time", "ends_at", "end_date", "submission_deadline"):
        if not end_date:
            end_date = to_iso_date(str(item.get(field, ""))) or end_date

    if start_date and end_date:
        return start_date, end_date

    submission_range = str(item.get("submission_period_dates") or "")
    parsed_start, parsed_end = _parse_submission_period_dates(submission_range)
    start_date = start_date or parsed_start or ""
    end_date = end_date or parsed_end or ""
    return start_date, end_date


def _discover_devpost_hackathons() -> List[Dict[str, Any]]:
    headers = {
        "User-Agent": "hackathon-calendar-bot/1.0 (+https://cloud.google.com/functions)",
        "Accept": "application/json",
    }
    candidates: List[Dict[str, Any]] = []
    for page in range(1, 4):
        try:
            response = requests.get(DEVPOST_API_URL, headers=headers, params={"page": page}, timeout=30)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            LOGGER.warning("Devpost API fetch failed on page %s: %s", page, exc)
            continue

        items = payload.get("hackathons", [])
        if not isinstance(items, list) or not items:
            continue

        for item in items:
            if not isinstance(item, dict):
                continue
            url = (item.get("url") or "").strip()
            title = (item.get("title") or "").strip()
            if not url or not title:
                continue

            try:
                html = requests.get(url, headers=headers, timeout=30).text
                ld = extract_ldjson_event(html) or {}
            except Exception as exc:
                LOGGER.warning("Devpost detail fetch failed for %s: %s", url, exc)
                ld = {}

            location = ""
            location_obj = ld.get("location")
            if isinstance(location_obj, dict):
                address = location_obj.get("address")
                if isinstance(address, dict):
                    location = (str(address.get("addressLocality") or "") or str(address.get("name") or "")).strip()
                else:
                    location = str(location_obj.get("name") or "").strip()

            start_date, end_date = _resolve_devpost_dates(item, ld)

            candidates.append(
                {
                    "name": title,
                    "url": url,
                    "start_date": start_date,
                    "end_date": end_date,
                    "location": location or "unknown",
                    "description": str(ld.get("description") or item.get("tagline") or "").strip()[:4000],
                    "source_platform": "devpost_api",
                    "event_mode": "unknown",
                    "location_evidence": "Derived from Devpost event page metadata",
                    "evidence": "Discovered via Devpost API and event detail page",
                    "is_genuine": True,
                    "matches_skills": True,
                    "reason": "Candidate discovered from Devpost API; strict filters applied later.",
                    "confidence": 0.85,
                }
            )

    LOGGER.info("Devpost discovery produced %s candidates", len(candidates))
    return candidates


def _discover_gemini_grounded(skills_text: str) -> List[Dict[str, Any]]:
    start_date = datetime.utcnow().date()
    end_date = start_date + timedelta(days=CONFIG.discovery_window_days)
    source_domains = ", ".join(SOURCE_HINTS)

    prompt = f"""
You are a hackathon discovery + filtering agent.
Use web search grounding to find upcoming software/engineering hackathons that start between {start_date.isoformat()} and {end_date.isoformat()}.

Prioritize these sources (not exclusive): {source_domains}

Return STRICT JSON with this shape:
{{
  "hackathons": [
    {{
      "name": "string",
      "url": "string",
      "start_date": "YYYY-MM-DD",
      "end_date": "YYYY-MM-DD",
      "location": "string",
      "description": "string",
      "source_platform": "string",
      "event_mode": "fully_online|hybrid|in_person|unknown",
      "location_evidence": "short quote/paraphrase proving location/mode from source",
      "evidence": "short evidence of why this is a real hackathon page",
      "is_genuine": true,
      "matches_skills": true,
      "reason": "string",
      "confidence": 0.0
    }}
  ]
}}

Rules:
- Include only events with a specific registration/details page URL.
- Exclude generic homepage URLs unless they are the specific event page.
- Dates must be exact ISO (YYYY-MM-DD).
- Maximum {CONFIG.max_discovery_results} events.
- Do not include events that already ended.
- Search broadly and deeply across multiple listing/result pages, not just top results.
- Focus heavily on Devpost listing pages and event detail pages.
- Prioritize Australia/Brisbane sources and fully-online global events.
- Include both matching and non-matching candidates, and use `matches_skills` + `reason` to explain.
- Exclude Devfolio links and do not include devfolio.co as a source.
- Exclude India-based events (location in India, India-only eligibility, or India-hosted pages).

SKILLS.md criteria:
{skills_text}
    """.strip()

    parsed = call_gemini_json(prompt, use_search=True)
    hackathons = parsed.get("hackathons", [])
    return hackathons if isinstance(hackathons, list) else []


def discover_hackathons(skills_text: str) -> List[Dict[str, Any]]:
    discovered: List[Dict[str, Any]] = []
    discovered.extend(_discover_devpost_hackathons())
    discovered.extend(_discover_gemini_grounded(skills_text))

    output: List[Dict[str, Any]] = []
    seen_urls: set[str] = set()
    for item in discovered:
        raw_url = (item.get("url") or "").strip()
        if not raw_url:
            continue
        url = normalize_url(raw_url)
        if url in seen_urls:
            continue
        seen_urls.add(url)
        item["url"] = url
        output.append(item)
        if len(output) >= CONFIG.max_discovery_results:
            break
    return output
