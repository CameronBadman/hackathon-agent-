import os

PROSPECTIVE_SUMMARY = "Prospective Hackathons"
DEFAULT_COLLECTION = "hackathons"
DEFAULT_DISCOVERY_WINDOW_DAYS = 60
DEFAULT_MAX_DISCOVERY_RESULTS = 150
DEFAULT_QUALITY_SCORE_THRESHOLD = 0.45
DEFAULT_FINAL_INCLUDE_CONFIDENCE = 0.90
DEVPOST_API_URL = "https://devpost.com/api/hackathons"

SOURCE_HINTS = [
    "devpost.com/hackathons",
    "devpost.com/software/hackathons",
    "devpost.com/hackathons?challenge_type[]=online",
    "devpost.com/hackathons?location[]=australia",
    "devpost.com",
    "mlh.io",
    "lablab.ai",
    "dorahacks.io",
    "uqcs.org",
    "uqcs.org/events",
    "qut.edu.au",
    "uq.edu.au",
    "eventbrite.com/d/australia--brisbane/hackathon",
    "eventbrite.com/d/online/hackathon",
    "meetup.com/find/?keywords=hackathon%20brisbane",
    "meetup.com/find/?keywords=online%20hackathon",
    "hackathons.com.au",
    "eventbrite.com",
]

TRUSTED_SOURCE_DOMAINS = {
    "devpost.com",
    "mlh.io",
    "lablab.ai",
    "dorahacks.io",
    "hackathons.com.au",
    "eventbrite.com",
    "meetup.com",
    "uqcs.org",
    "qut.edu.au",
    "uq.edu.au",
}

SUSPICIOUS_TITLE_PREFIXES = (
    "international hackathon on ",
    "global hackathon on ",
)

BRISBANE_KEYWORDS = (
    "brisbane",
    "brisbane qld",
    "brisbane, qld",
    "brisbane queensland",
    "queensland, australia",
    "qld, australia",
)

ONLINE_STRONG_KEYWORDS = (
    "fully online",
    "100% online",
    "online-only",
    "online only",
    "remote only",
    "virtual hackathon",
)

ONLINE_WEAK_KEYWORDS = (
    "online",
    "virtual",
    "remote",
)

IN_PERSON_OR_HYBRID_KEYWORDS = (
    "in-person",
    "in person",
    "on-site",
    "onsite",
    "venue",
    "campus",
    "hybrid",
    "offline",
)

INDIA_GEO_KEYWORDS = (
    " india ",
    ", india",
    " india,",
    "new delhi",
    "delhi",
    "mumbai",
    "bengaluru",
    "bangalore",
    "hyderabad",
    "chennai",
    "kolkata",
    "pune",
    "ahmedabad",
    "gurgaon",
    "gurugram",
    "noida",
)


class Config:
    def __init__(self) -> None:
        self.project_id = (
            os.getenv("PROJECT_ID")
            or os.getenv("GOOGLE_CLOUD_PROJECT")
            or os.getenv("GCP_PROJECT")
        )
        if not self.project_id:
            raise RuntimeError("PROJECT_ID is required")

        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.gemini_secret = os.getenv("GEMINI_API_KEY_SECRET_NAME", "gemini-api-key")
        self.collection_name = os.getenv("FIRESTORE_COLLECTION", DEFAULT_COLLECTION)
        self.discovery_window_days = int(
            os.getenv("DISCOVERY_WINDOW_DAYS", str(DEFAULT_DISCOVERY_WINDOW_DAYS))
        )
        self.max_discovery_results = int(
            os.getenv("MAX_DISCOVERY_RESULTS", str(DEFAULT_MAX_DISCOVERY_RESULTS))
        )
        self.quality_score_threshold = float(
            os.getenv("QUALITY_SCORE_THRESHOLD", str(DEFAULT_QUALITY_SCORE_THRESHOLD))
        )
        self.final_include_confidence = float(
            os.getenv("FINAL_INCLUDE_CONFIDENCE", str(DEFAULT_FINAL_INCLUDE_CONFIDENCE))
        )
        self.oauth_client_id_secret = os.getenv(
            "GOOGLE_OAUTH_CLIENT_ID_SECRET_NAME", "google-oauth-client-id"
        )
        self.oauth_client_secret_secret = os.getenv(
            "GOOGLE_OAUTH_CLIENT_SECRET_SECRET_NAME", "google-oauth-client-secret"
        )
        self.oauth_refresh_token_secret = os.getenv(
            "GOOGLE_OAUTH_REFRESH_TOKEN_SECRET_NAME", "google-oauth-refresh-token"
        )


CONFIG = Config()
