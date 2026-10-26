"""Runtime settings, read from the environment (.env is loaded if present).

SAMPLE_MODE=true means: no Zetaris, no Nightshift, no Companies House, no network.
The agents still run their real logic, but over the cached council data in
data/sample and with a deterministic template in place of the model.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)


def _truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


def _secret(name: str) -> str:
    """A credential from the environment, or "" when it is unset or still the .env.example placeholder.

    A judge who copies .env.example to .env gets values like "your-zetaris-api-key"; those must not
    switch the app into live mode against services that are not there.
    """
    v = (os.getenv(name) or "").strip()
    return "" if v.lower().startswith("your-") else v


@dataclass
class Settings:
    sample_mode: bool = field(default_factory=lambda: _truthy(os.getenv("SAMPLE_MODE", "false")))
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8000")))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))

    # Zetaris (data layer)
    zetaris_rest_url: str = field(default_factory=lambda: os.getenv("ZETARIS_REST_URL", "http://localhost:8888/api/v1.0"))
    zetaris_org_id: str = field(default_factory=lambda: os.getenv("ZETARIS_ORG_ID", "1"))
    zetaris_api_key: str = field(default_factory=lambda: _secret("ZETARIS_API_KEY"))

    # Meterless Nightshift (primary AI provider)
    meterless_base_url: str = field(default_factory=lambda: os.getenv("METERLESS_BASE_URL", "http://127.0.0.1:8088/v1"))
    meterless_runtime_token: str = field(default_factory=lambda: _secret("METERLESS_RUNTIME_TOKEN"))
    meterless_model: str = field(default_factory=lambda: os.getenv("METERLESS_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b"))

    # Optional: Companies House (supplier identity)
    companies_house_api_key: str = field(default_factory=lambda: _secret("COMPANIES_HOUSE_API_KEY"))

    # Domain
    vesting_day: str = field(default_factory=lambda: os.getenv("VESTING_DAY", "2027-04-01"))
    cliff_window_days: int = field(default_factory=lambda: int(os.getenv("CLIFF_WINDOW_DAYS", "180")))

    # Paths
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", str(ROOT / "data" / "sample"))))
    memory_dir: Path = field(default_factory=lambda: Path(os.getenv("MEMORY_DIR", str(ROOT / "data" / "memory"))))
    logs_dir: Path = field(default_factory=lambda: Path(os.getenv("LOGS_DIR", str(ROOT / "logs"))))

    def effective_sample_mode(self, requested: bool | None) -> bool:
        """The environment can force sample mode; a request can only ask for it."""
        if self.sample_mode:
            return True
        if requested:
            return True
        # Live mode needs the two mandatory services configured; otherwise fall back.
        return not (self.zetaris_api_key and self.meterless_runtime_token)


settings = Settings()
