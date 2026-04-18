import json
import re
from typing import Any, Dict, List, Optional

import requests


def download_page_text(url: str, max_chars: int = 250000) -> str:
    headers = {"User-Agent": "hackathon-calendar-bot/1.0 (+https://cloud.google.com/functions)"}
    response = requests.get(url, headers=headers, timeout=25)
    response.raise_for_status()
    text = response.text
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def extract_ldjson_event(html: str) -> Optional[Dict[str, Any]]:
    matches = re.findall(
        r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    for raw in matches:
        text = raw.strip()
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue

        nodes: List[Any]
        if isinstance(parsed, list):
            nodes = parsed
        elif isinstance(parsed, dict):
            nodes = parsed.get("@graph") if isinstance(parsed.get("@graph"), list) else [parsed]
        else:
            continue

        for node in nodes:
            if isinstance(node, dict) and "event" in str(node.get("@type", "")).lower():
                return node
    return None
