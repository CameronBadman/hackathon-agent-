import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import functions_framework
from flask import Request
from google.cloud import firestore
from google.cloud import secretmanager
from google.oauth2 import id_token
from google.oauth2.credentials import Credentials
from google.auth.transport import requests as auth_requests
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)

DEFAULT_COLLECTION = "hackathons"
DEFAULT_SYSTEM_COLLECTION = "_system"
COMMITTED_SUMMARY = "Committed Hackathons"
PROSPECTIVE_SUMMARY = "Prospective Hackathons"


class Config:
    def __init__(self) -> None:
        self.project_id = (
            os.getenv("PROJECT_ID")
            or os.getenv("GOOGLE_CLOUD_PROJECT")
            or os.getenv("GCP_PROJECT")
        )
        if not self.project_id:
            raise RuntimeError("PROJECT_ID is required")

        self.collection_name = os.getenv("FIRESTORE_COLLECTION", DEFAULT_COLLECTION)
        self.system_collection_name = os.getenv("SYSTEM_COLLECTION", DEFAULT_SYSTEM_COLLECTION)

        self.target_email_secret = os.getenv("TARGET_EMAIL_SECRET_NAME", "target-account-email")
        self.oauth_client_id_secret = os.getenv("GOOGLE_OAUTH_CLIENT_ID_SECRET_NAME", "google-oauth-client-id")
        self.oauth_client_secret_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET_SECRET_NAME", "google-oauth-client-secret")
        self.oauth_refresh_token_secret = os.getenv(
            "GOOGLE_OAUTH_REFRESH_TOKEN_SECRET_NAME", "google-oauth-refresh-token"
        )
        self.webhook_token_secret = os.getenv("WEBHOOK_SECRET_NAME", "calendar-webhook-token")

        self.scheduler_audience = os.getenv("SCHEDULER_AUDIENCE")
        self.scheduler_sa_email = os.getenv("SCHEDULER_INVOKER_SA")


CONFIG = Config()
SM_CLIENT = secretmanager.SecretManagerServiceClient()
DB = firestore.Client(project=CONFIG.project_id)


def _access_secret(secret_name: str) -> str:
    resource = f"projects/{CONFIG.project_id}/secrets/{secret_name}/versions/latest"
    response = SM_CLIENT.access_secret_version(request={"name": resource})
    return response.payload.data.decode("utf-8").strip()


def _calendar_client() -> Any:
    credentials = Credentials(
        token=None,
        refresh_token=_access_secret(CONFIG.oauth_refresh_token_secret),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=_access_secret(CONFIG.oauth_client_id_secret),
        client_secret=_access_secret(CONFIG.oauth_client_secret_secret),
        scopes=["https://www.googleapis.com/auth/calendar"],
    )
    credentials.refresh(auth_requests.Request())
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def _system_doc(doc_id: str) -> firestore.DocumentReference:
    return DB.collection(CONFIG.system_collection_name).document(doc_id)


def _watch_state() -> Dict[str, Any]:
    snap = _system_doc("watch_state").get()
    return snap.to_dict() if snap.exists else {}


def _save_watch_state(values: Dict[str, Any]) -> None:
    values["updated_at"] = firestore.SERVER_TIMESTAMP
    _system_doc("watch_state").set(values, merge=True)


def _verify_scheduler_oidc(request: Request) -> bool:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        LOGGER.warning("Renew request missing bearer token")
        return False

    token = auth_header.split(" ", 1)[1]
    candidate_audiences = []
    forwarded_proto = (request.headers.get("X-Forwarded-Proto") or "").strip()
    forwarded_host = (request.headers.get("Host") or "").strip()
    if forwarded_proto and forwarded_host:
        candidate_audiences.append(f"{forwarded_proto}://{forwarded_host}".rstrip("/"))

    if CONFIG.scheduler_audience:
        candidate_audiences.append(CONFIG.scheduler_audience.rstrip("/"))
    candidate_audiences.append(request.base_url.rstrip("/"))
    candidate_audiences.append(request.url_root.rstrip("/"))

    audiences = list(dict.fromkeys([aud for aud in candidate_audiences if aud]))
    request_adapter = auth_requests.Request()
    token_info = None
    last_error = None

    for audience in audiences:
        try:
            token_info = id_token.verify_oauth2_token(
                token,
                request_adapter,
                audience=audience,
            )
            break
        except Exception as exc:
            last_error = exc

    if token_info is None:
        LOGGER.warning(
            "Failed scheduler OIDC verification for audiences=%s error=%s",
            audiences,
            str(last_error),
        )
        return False

    if CONFIG.scheduler_sa_email and not token_info.get("email"):
        LOGGER.warning("Scheduler token is valid but missing email claim")
        return False

    if CONFIG.scheduler_sa_email and token_info.get("email", "").lower() != CONFIG.scheduler_sa_email.lower():
        LOGGER.warning("Unexpected scheduler caller email: %s", token_info.get("email"))
        return False

    return True


def _list_events_with_sync(
    service: Any, calendar_id: str, sync_token: Optional[str]
) -> Tuple[List[Dict[str, Any]], str]:
    all_events: List[Dict[str, Any]] = []
    page_token = None
    next_sync_token: Optional[str] = None

    while True:
        params = {
            "calendarId": calendar_id,
            "singleEvents": True,
            "showDeleted": True,
            "maxResults": 250,
            "pageToken": page_token,
        }
        if sync_token:
            params["syncToken"] = sync_token
        else:
            params["timeMin"] = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

        response = service.events().list(**params).execute()
        all_events.extend(response.get("items", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            next_sync_token = response.get("nextSyncToken")
            break

    if not next_sync_token:
        raise RuntimeError("Google Calendar did not return nextSyncToken")

    return all_events, next_sync_token


def _find_or_create_calendar(service: Any, settings_key: str, summary: str) -> str:
    settings_doc = _system_doc("calendar_settings")
    existing = settings_doc.get().to_dict() if settings_doc.get().exists else {}
    calendar_id = existing.get(settings_key)

    if calendar_id:
        try:
            service.calendars().get(calendarId=calendar_id).execute()
            return calendar_id
        except HttpError:
            LOGGER.warning("Stored calendar no longer valid: %s", calendar_id)

    page_token = None
    while True:
        response = service.calendarList().list(pageToken=page_token).execute()
        for cal in response.get("items", []):
            if cal.get("summary") == summary:
                calendar_id = cal.get("id")
                settings_doc.set(
                    {
                        settings_key: calendar_id,
                        "updated_at": firestore.SERVER_TIMESTAMP,
                    },
                    merge=True,
                )
                return calendar_id
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    tz = "Australia/Brisbane"
    created = service.calendars().insert(body={"summary": summary, "timeZone": tz}).execute()
    calendar_id = created["id"]
    settings_doc.set(
        {
            settings_key: calendar_id,
            "updated_at": firestore.SERVER_TIMESTAMP,
        },
        merge=True,
    )
    return calendar_id


def _copy_event_to_committed(service: Any, event: Dict[str, Any], committed_calendar_id: str) -> str:
    copied = {
        "summary": event.get("summary"),
        "description": event.get("description"),
        "start": event.get("start"),
        "end": event.get("end"),
        "location": event.get("location"),
    }
    created = service.events().insert(calendarId=committed_calendar_id, body=copied).execute()
    return created["id"]


def _attendee_response(event: Dict[str, Any], email: str) -> Optional[str]:
    for attendee in event.get("attendees", []):
        if attendee.get("email", "").lower() == email.lower():
            return attendee.get("responseStatus")
    return None


def _sync_status_from_events(service: Any, changed_events: List[Dict[str, Any]]) -> Dict[str, int]:
    target_email = _access_secret(CONFIG.target_email_secret)
    committed_calendar_id = _find_or_create_calendar(
        service, "committed_calendar_id", COMMITTED_SUMMARY
    )
    collection = DB.collection(CONFIG.collection_name)

    counts = {"checked": 0, "committed": 0, "declined": 0, "ignored": 0}

    for event in changed_events:
        event_id = event.get("id")
        if not event_id:
            counts["ignored"] += 1
            continue

        docs = list(collection.where("event_id", "==", event_id).limit(1).stream())
        if not docs:
            counts["ignored"] += 1
            continue

        counts["checked"] += 1
        doc = docs[0]
        data = doc.to_dict()
        status = _attendee_response(event, target_email)

        if status == "accepted":
            if data.get("status") == "committed":
                continue
            committed_event_id = data.get("committed_event_id")
            if not committed_event_id:
                committed_event_id = _copy_event_to_committed(service, event, committed_calendar_id)
            doc.reference.set(
                {
                    "status": "committed",
                    "committed_event_id": committed_event_id,
                    "updated_at": firestore.SERVER_TIMESTAMP,
                },
                merge=True,
            )
            counts["committed"] += 1
            continue

        if status == "declined":
            doc.reference.set(
                {
                    "status": "declined",
                    "updated_at": firestore.SERVER_TIMESTAMP,
                },
                merge=True,
            )
            counts["declined"] += 1
            continue

    return counts


def _renew_channel(request: Request) -> Tuple[str, int]:
    if not _verify_scheduler_oidc(request):
        return "Unauthorized", 401

    service = _calendar_client()
    calendar_id = _find_or_create_calendar(
        service, "prospective_calendar_id", PROSPECTIVE_SUMMARY
    )
    state = _watch_state()

    if state.get("channel_id") and state.get("resource_id"):
        try:
            service.channels().stop(
                body={"id": state["channel_id"], "resourceId": state["resource_id"]}
            ).execute()
        except HttpError:
            LOGGER.exception("Failed to stop previous channel; continuing")

    sync_token = state.get("sync_token")
    if not sync_token:
        _, sync_token = _list_events_with_sync(service, calendar_id, None)

    channel_id = str(uuid.uuid4())
    forwarded_proto = (request.headers.get("X-Forwarded-Proto") or "https").split(",")[0].strip()
    forwarded_host = (request.headers.get("Host") or "").strip()
    if forwarded_host:
        webhook_url = f"{forwarded_proto}://{forwarded_host}{request.path}"
    else:
        webhook_url = request.base_url.replace("http://", "https://", 1)
    webhook_token = _access_secret(CONFIG.webhook_token_secret)

    watch_response = (
        service.events()
        .watch(
            calendarId=calendar_id,
            body={
                "id": channel_id,
                "type": "web_hook",
                "address": webhook_url,
                "token": webhook_token,
                "params": {"ttl": "604800"},
            },
        )
        .execute()
    )

    expiration_ms = watch_response.get("expiration")
    expiration_iso = None
    if expiration_ms:
        expiration_iso = datetime.fromtimestamp(
            int(expiration_ms) / 1000, tz=timezone.utc
        ).isoformat()

    _save_watch_state(
        {
            "channel_id": watch_response.get("id"),
            "resource_id": watch_response.get("resourceId"),
            "resource_uri": watch_response.get("resourceUri"),
            "expiration": expiration_iso,
            "sync_token": sync_token,
            "webhook_url": webhook_url,
        }
    )

    LOGGER.info("Renewed channel %s expiring at %s", watch_response.get("id"), expiration_iso)
    return json.dumps({"channel_id": watch_response.get("id"), "expiration": expiration_iso}), 200


def _handle_push_notification(request: Request) -> Tuple[str, int]:
    expected_token = _access_secret(CONFIG.webhook_token_secret)
    provided_token = request.headers.get("X-Goog-Channel-Token", "")
    if provided_token != expected_token:
        return "Unauthorized", 401

    resource_state = request.headers.get("X-Goog-Resource-State", "")
    if resource_state == "sync":
        return "OK", 200

    service = _calendar_client()
    calendar_id = _find_or_create_calendar(
        service, "prospective_calendar_id", PROSPECTIVE_SUMMARY
    )
    state = _watch_state()
    sync_token = state.get("sync_token")

    try:
        events, next_sync_token = _list_events_with_sync(service, calendar_id, sync_token)
    except HttpError as exc:
        if exc.resp.status == 410:
            events, next_sync_token = _list_events_with_sync(service, calendar_id, None)
        else:
            raise

    counts = _sync_status_from_events(service, events)
    _save_watch_state({"sync_token": next_sync_token})
    LOGGER.info("Webhook sync result: %s", counts)
    return json.dumps(counts), 200


@functions_framework.http
def webhook_entrypoint(request: Request):
    action = (request.args.get("action") or "").strip().lower()

    try:
        if action == "renew":
            body, status = _renew_channel(request)
            return body, status, {"Content-Type": "application/json"}

        body, status = _handle_push_notification(request)
        return body, status, {"Content-Type": "application/json"}
    except Exception:
        LOGGER.exception("Webhook handler failed")
        return "Internal Server Error", 500
