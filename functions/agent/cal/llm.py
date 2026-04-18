import json
import logging
import time
from typing import Any, Dict, Optional

import requests

from .config import CONFIG
from .services import access_secret

LOGGER = logging.getLogger(__name__)


def extract_model_json(data: Dict[str, Any]) -> Dict[str, Any]:
    candidates = data.get("candidates", [])
    if not candidates:
        return {}
    parts = candidates[0].get("content", {}).get("parts", [])
    text_part = next((p.get("text") for p in parts if "text" in p), "")
    if not text_part:
        return {}

    cleaned = text_part.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
    if not cleaned.startswith("{"):
        first = cleaned.find("{")
        last = cleaned.rfind("}")
        if first >= 0 and last > first:
            cleaned = cleaned[first : last + 1]
    return json.loads(cleaned)


def call_gemini_json(prompt: str, use_search: bool) -> Dict[str, Any]:
    api_key = access_secret(CONFIG.gemini_secret)
    endpoint = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{CONFIG.gemini_model}:generateContent"
    )
    payload: Dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2},
    }
    if use_search:
        payload["tools"] = [{"google_search": {}}]

    last_error: Optional[Exception] = None
    for attempt in range(4):
        try:
            response = requests.post(
                f"{endpoint}?key={api_key}",
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=90,
            )
            if response.status_code != 429:
                response.raise_for_status()
                return extract_model_json(response.json())

            wait_s = 4 * (2**attempt)
            LOGGER.warning("Gemini rate-limited (429), retrying in %ss", wait_s)
            time.sleep(wait_s)
            last_error = RuntimeError(f"Gemini 429 Too Many Requests after attempt {attempt + 1}")
        except requests.exceptions.RequestException as exc:
            wait_s = 4 * (2**attempt)
            LOGGER.warning("Gemini request error (%s), retrying in %ss", type(exc).__name__, wait_s)
            time.sleep(wait_s)
            last_error = RuntimeError(f"Gemini request error after attempt {attempt + 1}: {exc}")

    if last_error:
        raise last_error
    raise RuntimeError("Gemini request failed without response")
