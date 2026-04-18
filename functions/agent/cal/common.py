import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urlunparse


def load_skills_file(base_dir: str) -> str:
    return (Path(base_dir).resolve().parent / "SKILLS.md").read_text(encoding="utf-8")


def normalize_url(raw_url: str) -> str:
    parsed = urlparse(raw_url.strip())
    clean = parsed._replace(query="", fragment="")
    return urlunparse(clean)


def doc_id_for_url(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def parse_date(value: str) -> Optional[datetime.date]:
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def to_iso_date(value: str) -> Optional[str]:
    if not value:
        return None
    cleaned = value.strip()
    if len(cleaned) >= 10 and re.match(r"^\d{4}-\d{2}-\d{2}", cleaned):
        return cleaned[:10]
    parsed = parse_date(cleaned)
    return parsed.isoformat() if parsed else None


def domain_from_url(url: str) -> str:
    host = (urlparse(url).netloc or "").lower().strip()
    return host[4:] if host.startswith("www.") else host
