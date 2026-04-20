import base64
import json
import logging
import re
from typing import Any, Dict, List

from .calendar_sync import calendar_client, create_calendar_event, get_prospective_calendar
from .common import normalize_url, parse_date
from .config import CONFIG
from .evidence import download_page_text
from .llm import call_gemini_json
from .score import quality_score
from .sources import discover_hackathons
from .state import already_processed, store_filtered, store_pending

LOGGER = logging.getLogger(__name__)


def _extract_event_source_url(event: Dict[str, Any]) -> str:
    source = event.get("source", {})
    if isinstance(source, dict):
        url = (source.get("url") or "").strip()
        if url:
            return url
    description = str(event.get("description", ""))
    match = re.search(r"Source:\s*(https?://\S+)", description, flags=re.IGNORECASE)
    return (match.group(1).strip() if match else "")


def _llm_final_verdict(skills_text: str, candidate: Dict[str, Any], page_text: str) -> tuple[bool, str, float, Dict[str, str]]:
    prompt = f"""
You are the final decision-maker for whether to include a hackathon event.
Use the full page text plus event fields, then decide if this is a genuinely strong fit for SKILLS.md.

Return STRICT JSON:
{{
  "include": true,
  "reason": "short concrete reason tied to criteria",
  "confidence": 0.0,
  "location_verdict": "brisbane|fully_online|reject",
  "quality_verdict": "strong|okay|weak|reject",
  "technical_fit_verdict": "strong|okay|weak|reject",
  "legitimacy_verdict": "strong|okay|weak|reject",
  "audience_fit_verdict": "strong|okay|weak|reject",
  "evidence": "brief quote/paraphrase from page text"
}}

Decision Specification:
- Prioritize full page text over listing metadata.
- Be conservative. If key facts are missing/ambiguous, return include=false.
- Include=true only when ALL of the following pass:
  1) Location pass: clearly Brisbane in-person OR clearly fully-online/remote participation.
  2) Technical pass: substantial software/ML/AI/systems/hardware build challenge.
  3) Quality pass: concrete structure (challenge scope, timeline/deadline, submission format, judging criteria, prize/value proposition).
  4) Audience pass: primary audience is serious builders/professionals/university-level developers, not school-age or classroom-style participants.
  5) Legitimacy pass: credible organizer and event context are explicit (real host/brand/community, concrete logistics, and a specific event page).
- Set include=false when event is generic/low-detail, mostly non-technical, education-first, workshop/classroom-first, youth/school-targeted, or location policy is not met.
- Reject if the page framing is mainly learning/tutorial/intro course style rather than a competitive technical build event.
- Reject if participation appears restricted to school-age cohorts (e.g., high school, middle school, teen-only) or if maturity/professional signal is weak.
- Prefer events with clear competitive rigor: explicit judging rubric, deliverable expectations, and substantive technical evaluation.
- Confidence guidance:
  - >=0.93: explicit, direct evidence for all criteria.
  - 0.70-0.84: mostly clear, minor gaps.
  - <0.70: meaningful ambiguity.
- Keep reason short and criterion-based.
- Evidence must reference concrete page signals, not assumptions.

SKILLS.md:
{skills_text}

Event:
{json.dumps(candidate, ensure_ascii=False)}

Full page text:
{page_text}
    """.strip()

    try:
        parsed = call_gemini_json(prompt, use_search=False)
    except Exception as exc:
        return False, f"Final LLM decision failed: {exc}", 0.0, {}

    raw_include = bool(parsed.get("include", False))
    reason = (parsed.get("reason") or parsed.get("evidence") or "No reason provided").strip()
    try:
        confidence = float(parsed.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    location_verdict = str(parsed.get("location_verdict", "reject")).strip().lower()
    quality_verdict = str(parsed.get("quality_verdict", "reject")).strip().lower()
    technical_fit_verdict = str(parsed.get("technical_fit_verdict", "reject")).strip().lower()
    legitimacy_verdict = str(parsed.get("legitimacy_verdict", "reject")).strip().lower()
    audience_fit_verdict = str(parsed.get("audience_fit_verdict", "reject")).strip().lower()

    include = (
        raw_include
        and location_verdict in {"brisbane", "fully_online"}
        and quality_verdict in {"strong", "okay"}
        and technical_fit_verdict in {"strong", "okay"}
        and legitimacy_verdict in {"strong", "okay"}
        and audience_fit_verdict in {"strong", "okay"}
    )
    if raw_include and not include:
        reason = f"Rejected: structured verdicts failed strict include criteria. {reason}"

    verdicts = {
        "location_verdict": location_verdict,
        "quality_verdict": quality_verdict,
        "technical_fit_verdict": technical_fit_verdict,
        "legitimacy_verdict": legitimacy_verdict,
        "audience_fit_verdict": audience_fit_verdict,
    }
    return include, reason, confidence, verdicts


def _llm_page_normalize(skills_text: str, candidate: Dict[str, Any], page_text: str) -> Dict[str, Any]:
    prompt = f"""
You are normalizing a hackathon listing from its full event page text.
Return STRICT JSON with this shape:
{{
  "name": "string",
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD",
  "location": "string",
  "event_mode": "fully_online|hybrid|in_person|unknown",
  "is_genuine": true,
  "matches_skills": true,
  "reason": "short reason tied to SKILLS.md",
  "location_evidence": "short quote/paraphrase",
  "evidence": "short quote/paraphrase proving this is a real hackathon",
  "confidence": 0.0
}}

Rules:
- Prioritize full page text over prefilled candidate fields.
- If page text clearly indicates "Brisbane edition"/Brisbane venue, mark as Brisbane location.
- Mark fully-online only when the page supports remote/virtual participation.
- Be strict about factual extraction, but do not reject solely because listing metadata is incomplete.

SKILLS.md:
{skills_text}

Candidate fields:
{json.dumps(candidate, ensure_ascii=False)}

Full page text:
{page_text}
    """.strip()
    return call_gemini_json(prompt, use_search=False)


def _prune_existing_prospective_events(
    calendar_service: Any,
    calendar_id: str,
    skills_text: str,
) -> int:
    purged = 0
    page_token = None
    while True:
        response = calendar_service.events().list(
            calendarId=calendar_id,
            maxResults=250,
            pageToken=page_token,
            singleEvents=True,
            showDeleted=False,
        ).execute()
        items = response.get("items", [])
        for event in items:
            event_id = event.get("id")
            if not event_id:
                continue
            source_url = _extract_event_source_url(event)
            page_text = ""
            if source_url:
                try:
                    page_text = download_page_text(source_url)
                except Exception:
                    page_text = ""

            candidate = {
                "name": event.get("summary", ""),
                "url": source_url,
                "location": event.get("location", ""),
                "description": event.get("description", ""),
                "evidence": "",
                "location_evidence": "",
                "event_mode": "unknown",
            }
            try:
                include, _, confidence, _ = _llm_final_verdict(skills_text, candidate, page_text)
            except Exception:
                include = True
                confidence = 1.0
            if include and confidence >= CONFIG.final_include_confidence:
                continue
            try:
                calendar_service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
                purged += 1
            except Exception:
                LOGGER.exception("Failed deleting non-compliant prospective event: %s", event_id)

        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return purged


def _existing_event_index_by_source_url(calendar_service: Any, calendar_id: str) -> Dict[str, str]:
    index: Dict[str, str] = {}
    page_token = None
    while True:
        response = calendar_service.events().list(
            calendarId=calendar_id,
            maxResults=250,
            pageToken=page_token,
            singleEvents=True,
            showDeleted=False,
        ).execute()
        for event in response.get("items", []):
            event_id = event.get("id", "")
            if not event_id:
                continue
            source_url = normalize_url(_extract_event_source_url(event))
            if not source_url:
                continue
            index[source_url] = event_id
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return index


def process_hackathons(hackathons: List[Dict[str, Any]], skills_text: str) -> Dict[str, int]:
    cal = calendar_client()
    calendar_id = get_prospective_calendar(cal)
    seen_urls: set[str] = set()
    counts = {"seen": 0, "pending": 0, "filtered": 0, "skipped": 0, "errors": 0, "purged": 0}

    # Keep prospective calendar aligned with full-page LLM quality/location decisions.
    counts["purged"] = _prune_existing_prospective_events(cal, calendar_id, skills_text)
    existing_source_events = _existing_event_index_by_source_url(cal, calendar_id)

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
        # Do not hard-reject on discovery-stage SKILLS verdict; re-check with full page text below.
        if merged.get("matches_skills", None) is False:
            LOGGER.info("Candidate flagged by discovery-stage skills check; continuing to strict page validation: %s", url)

        try:
            page_text = download_page_text(url)
        except Exception as exc:
            store_filtered(merged, f"Filtered: failed to fetch event page for strict location validation: {exc}")
            counts["filtered"] += 1
            continue

        try:
            page_normalized = _llm_page_normalize(skills_text, merged, page_text)
            if isinstance(page_normalized, dict):
                for key in (
                    "name",
                    "start_date",
                    "end_date",
                    "location",
                    "event_mode",
                    "is_genuine",
                    "matches_skills",
                    "reason",
                    "location_evidence",
                    "evidence",
                    "confidence",
                ):
                    value = page_normalized.get(key)
                    if value not in (None, "", []):
                        merged[key] = value
        except Exception as exc:
            LOGGER.warning("Page normalization failed for %s: %s", url, exc)

        include, include_reason, include_confidence, _ = _llm_final_verdict(skills_text, merged, page_text)
        merged["reason"] = include_reason
        merged["confidence"] = include_confidence
        if not include or include_confidence < CONFIG.final_include_confidence:
            reason = include_reason if not include else f"Rejected: low decision confidence ({include_confidence:.2f})"
            store_filtered(merged, reason)
            counts["filtered"] += 1
            continue

        name = (merged.get("name") or "").strip()
        start = parse_date(merged.get("start_date", ""))
        end = parse_date(merged.get("end_date", ""))
        if not (name and start and end):
            store_filtered(merged, "Filtered due to incomplete required data after full-page extraction")
            counts["filtered"] += 1
            continue

        score = quality_score(item, merged)
        existing_event_id = existing_source_events.get(url)
        if existing_event_id:
            store_pending(merged, existing_event_id, score)
            LOGGER.info("Reused existing prospective event for url=%s event_id=%s", url, existing_event_id)
            counts["pending"] += 1
            continue

        try:
            created = create_calendar_event(cal, calendar_id, merged)
            event_id = created.get("id", "")
            existing_source_events[url] = event_id
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
