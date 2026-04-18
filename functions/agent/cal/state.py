import logging
from typing import Any, Dict, Optional

from google.cloud import firestore

from .common import doc_id_for_url
from .config import CONFIG

LOGGER = logging.getLogger(__name__)
DB = firestore.Client(project=CONFIG.project_id)


def _doc_ref_for_url(url: str) -> firestore.DocumentReference:
    return DB.collection(CONFIG.collection_name).document(doc_id_for_url(url))


def already_processed(url: str) -> bool:
    return _doc_ref_for_url(url).get().exists


def store_filtered(hackathon: Dict[str, Any], reason: str, quality_score: Optional[float] = None) -> None:
    url = (hackathon.get("url") or "").strip()
    if url:
        _doc_ref_for_url(url).set(
            {
                "status": "filtered",
                "url": url,
                "name": hackathon.get("name"),
                "start_date": hackathon.get("start_date"),
                "end_date": hackathon.get("end_date"),
                "location": hackathon.get("location"),
                "description": hackathon.get("description"),
                "reason": reason,
                "quality_score": quality_score,
                "source_platform": hackathon.get("source_platform"),
                "created_at": firestore.SERVER_TIMESTAMP,
                "updated_at": firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )
    LOGGER.info(
        "Filtered candidate: name=%s url=%s reason=%s quality_score=%s",
        hackathon.get("name"),
        hackathon.get("url"),
        reason,
        quality_score,
    )


def store_pending(hackathon: Dict[str, Any], event_id: str, quality_score: float) -> None:
    url = (hackathon.get("url") or "").strip()
    if not url:
        return
    _doc_ref_for_url(url).set(
        {
            "status": "pending",
            "url": url,
            "event_id": event_id,
            "name": hackathon.get("name"),
            "start_date": hackathon.get("start_date"),
            "end_date": hackathon.get("end_date"),
            "location": hackathon.get("location"),
            "description": hackathon.get("description"),
            "reason": hackathon.get("reason"),
            "quality_score": quality_score,
            "source_platform": hackathon.get("source_platform"),
            "created_at": firestore.SERVER_TIMESTAMP,
            "updated_at": firestore.SERVER_TIMESTAMP,
        },
        merge=True,
    )
