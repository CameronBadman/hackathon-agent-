from datetime import timedelta
from typing import Any, Dict

from google.auth.transport import requests as auth_requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from .common import parse_date
from .config import CONFIG, PROSPECTIVE_SUMMARY
from .services import access_secret


def calendar_client() -> Any:
    credentials = Credentials(
        token=None,
        refresh_token=access_secret(CONFIG.oauth_refresh_token_secret),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=access_secret(CONFIG.oauth_client_id_secret),
        client_secret=access_secret(CONFIG.oauth_client_secret_secret),
        scopes=["https://www.googleapis.com/auth/calendar"],
    )
    credentials.refresh(auth_requests.Request())
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def find_or_create_calendar(service: Any, summary: str) -> str:
    page_token = None
    while True:
        response = service.calendarList().list(pageToken=page_token).execute()
        for cal in response.get("items", []):
            if cal.get("summary") == summary:
                return cal["id"]
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    created = service.calendars().insert(body={"summary": summary, "timeZone": "Australia/Brisbane"}).execute()
    return created["id"]


def create_calendar_event(calendar_service: Any, prospective_calendar_id: str, hackathon: Dict[str, Any]) -> Dict[str, Any]:
    start = parse_date(hackathon["start_date"])
    end = parse_date(hackathon["end_date"])
    if not start or not end:
        raise ValueError("Invalid dates")
    if end < start:
        raise ValueError("End date before start date")

    body: Dict[str, Any] = {
        "summary": hackathon["name"],
        "description": "\n".join(
            [
                hackathon.get("description", ""),
                "",
                f"Source: {hackathon.get('url', '')}",
                f"Match rationale: {hackathon.get('reason', '')}",
            ]
        ).strip(),
        "start": {"date": start.isoformat()},
        "end": {"date": (end + timedelta(days=1)).isoformat()},
        "location": hackathon.get("location", ""),
        "transparency": "transparent",
    }
    url = (hackathon.get("url") or "").strip()
    if url:
        body["source"] = {"title": "Hackathon Listing", "url": url}

    return (
        calendar_service.events()
        .insert(calendarId=prospective_calendar_id, body=body, sendUpdates="all")
        .execute()
    )


def get_prospective_calendar(service: Any) -> str:
    return find_or_create_calendar(service, PROSPECTIVE_SUMMARY)
