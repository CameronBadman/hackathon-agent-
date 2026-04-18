import base64
import json
import logging
from typing import Any, Dict, List

from .calendar_sync import calendar_client, create_calendar_event, get_prospective_calendar
from .common import normalize_url, parse_date
from .config import CONFIG
from .evidence import download_page_text
from .rules import build_location_policy, location_gate
from .score import quality_score
from .sources import discover_hackathons
from .state import already_processed, store_filtered, store_pending

LOGGER = logging.getLogger(__name__)


def process_hackathons(hackathons: List[Dict[str, Any]], skills_text: str) -> Dict[str, int]:
    cal = calendar_client()
    calendar_id = get_prospective_calendar(cal)
    location_policy = build_location_policy(skills_text)
    seen_urls: set[str] = set()
    counts = {"seen": 0, "pending": 0, "filtered": 0, "skipped": 0, "errors": 0}

    for item in hackathons:
        counts["seen"] += 1
        raw_url = (item.get("url") or "").strip()
        if not raw_url:
            counts["errors"] += 1
            continue

        url = normalize_url(raw_url)
        item["url"] = url
        if url in seen_urls or already_processed(url):
            counts["skipped"] += 1
            continue
        seen_urls.add(url)

        merged = dict(item)
        merged["url"] = url
        score = quality_score(item, merged)

        reason = (merged.get("reason") or "No reason provided").strip()
        if score < CONFIG.quality_score_threshold:
            store_filtered(merged, f"Filtered: quality score {score:.2f} below threshold {CONFIG.quality_score_threshold:.2f}. {reason}", score)
            counts["filtered"] += 1
            continue
        if not bool(merged.get("is_genuine", False)):
            store_filtered(merged, f"Not genuine: {reason}", score)
            counts["filtered"] += 1
            continue
        if not bool(merged.get("matches_skills", False)):
            store_filtered(merged, reason, score)
            counts["filtered"] += 1
            continue

        name = (merged.get("name") or "").strip()
        start = parse_date(merged.get("start_date", ""))
        end = parse_date(merged.get("end_date", ""))
        if not (name and start and end):
            store_filtered(merged, "Filtered due to incomplete required data", score)
            counts["filtered"] += 1
            continue

        try:
            page_text = download_page_text(url)
        except Exception as exc:
            store_filtered(merged, f"Filtered: failed to fetch event page for strict location validation: {exc}", score)
            counts["filtered"] += 1
            continue

        passes_location, location_reason = location_gate(merged, page_text, location_policy)
        if not passes_location:
            store_filtered(merged, location_reason, score)
            counts["filtered"] += 1
            continue

        try:
            created = create_calendar_event(cal, calendar_id, merged)
            event_id = created.get("id", "")
            store_pending(merged, event_id, score)
            LOGGER.info("Created prospective event: name=%s event_id=%s quality_score=%.2f", name, event_id, score)
            counts["pending"] += 1
        except Exception:
            counts["errors"] += 1
            LOGGER.exception("Failed processing hackathon: %s", item)

    return counts


def run_once(cloud_event: Any, skills_text: str) -> str:
    if cloud_event and getattr(cloud_event, "data", None):
        message = cloud_event.data.get("message", {})
        data = message.get("data")
        if data:
            decoded = base64.b64decode(data).decode("utf-8")
            LOGGER.info("Scheduler payload: %s", decoded)

    try:
        hackathons = discover_hackathons(skills_text)
        counts = process_hackathons(hackathons, skills_text)
    except Exception as exc:
        if (
            "429" in str(exc)
            or "Too Many Requests" in str(exc)
            or "Read timed out" in str(exc)
            or "Gemini request error" in str(exc)
        ):
            counts = {"seen": 0, "pending": 0, "filtered": 0, "skipped": 0, "errors": 1}
            LOGGER.error("Gemini throttled this run; marking failed-but-acked: %s", exc)
        else:
            raise

    LOGGER.info("Run complete: %s", counts)
    return json.dumps(counts)
