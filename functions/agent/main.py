import logging
from typing import Any, Dict

import functions_framework

from cal.common import load_skills_file
from cal.orchestrator import run_once

LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)


@functions_framework.cloud_event
def run_agent(cloud_event: Any) -> str:
    skills_text = load_skills_file(__file__)
    return run_once(cloud_event, skills_text)


if __name__ == "__main__":
    class _Event:
        data: Dict[str, Any] = {}

    print(run_agent(_Event()))
