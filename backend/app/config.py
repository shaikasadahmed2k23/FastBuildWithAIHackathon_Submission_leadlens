"""Runtime settings and the ideal-customer-profile (ICP) used by scoring."""

from datetime import datetime
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent
DATA_DIR = BACKEND_DIR / "data"

# All time-based logic (seeding, staleness, recency, intent windows) is computed
# relative to this fixed instant so scores and evals are reproducible.
AS_OF = datetime(2026, 9, 15, 12, 0, 0)
AS_OF_SQL = f"TIMESTAMP '{AS_OF:%Y-%m-%d %H:%M:%S}'"

STALE_DAYS = 90
INTENT_WINDOW_DAYS = 30
OPEN_STAGES = ("new", "contacted", "qualified", "proposal", "negotiation")
CLOSED_STAGES = ("won", "lost")
ALL_STAGES = OPEN_STAGES + CLOSED_STAGES
OWNERS = ("Maya Chen", "Daniel Ortiz", "Priya Nair", "Tom Becker", "Aisha Bello", "Lucas Martin", "Hana Sato", "Ravi Kumar")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"),
        extra="ignore",
    )

    groq_api_key: str = ""
    gemini_api_key: str = ""
    # llama-3.3-70b-versatile was retired from Groq; gpt-oss-120b is the largest general model there now.
    groq_model: str = "openai/gpt-oss-120b"
    # Only sent to reasoning models (gpt-oss). "low" keeps latency and token use down under free-tier limits.
    groq_reasoning_effort: str = "low"
    gemini_model: str = "gemini-3.8-flash"
    leadlens_db_path: str = str(DATA_DIR / "leadlens.duckdb")
    cors_origins: str = "http://localhost:3000"
    llm_timeout_s: float = 20.0

    @property
    def db_path(self) -> Path:
        path = Path(self.leadlens_db_path)
        return path if path.is_absolute() else REPO_DIR / path

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()


# Ideal customer profile. Points are the share of the 40-point Fit budget.
ICP = {
    "seniority_points": {  # max 16
        "c_level": 16,
        "vp": 14,
        "director": 11,
        "manager": 7,
        "individual": 3,
    },
    "size_bands": [  # (min_employees, points), max 14; first match wins
        (1000, 14),
        (200, 12),
        (50, 8),
        (10, 4),
        (0, 1),
    ],
    "industry_points": {  # max 10
        "Software": 10,
        "Fintech": 10,
        "Healthcare": 7,
        "E-commerce": 7,
        "Logistics": 5,
        "Manufacturing": 4,
        "Education": 3,
        "Media": 3,
    },
    "industry_default": 2,
}

# Intent weights per activity type (before recency decay). Max 40 after cap.
INTENT_WEIGHTS = {
    "demo_request": 14.0,
    "pricing_page_visit": 9.0,
    "meeting": 8.0,
    "email_reply": 6.0,
    "call": 4.0,
    "website_visit": 2.0,
    "email_open": 1.0,
}
