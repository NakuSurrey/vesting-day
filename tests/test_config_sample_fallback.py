"""A judge who copies .env.example to .env must land in SAMPLE_MODE, not in a broken live mode.

The official self-test is: clone, `cp .env.example .env`, run, POST a new input. Before this
guard, .env.example shipped SAMPLE_MODE=false with placeholder keys, so the app went live
against a Zetaris that was not there and returned UpstreamTimeout.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings

ROOT = Path(__file__).resolve().parents[1]
KEYS = ("ZETARIS_API_KEY", "METERLESS_RUNTIME_TOKEN", "COMPANIES_HOUSE_API_KEY", "SAMPLE_MODE")


def _env_example() -> dict[str, str]:
    out = {}
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)


def test_env_example_as_shipped_runs_in_sample_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    env = _env_example()
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    s = Settings()
    assert s.effective_sample_mode(None) is True
    assert s.zetaris_api_key == "" and s.meterless_runtime_token == ""   # placeholders read as unset


def test_placeholders_never_switch_on_live_mode_even_with_sample_mode_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAMPLE_MODE", "false")
    monkeypatch.setenv("ZETARIS_API_KEY", "your-zetaris-api-key")
    monkeypatch.setenv("METERLESS_RUNTIME_TOKEN", "your-nightshift-runtime-token")
    assert Settings().effective_sample_mode(None) is True


def test_real_keys_with_sample_mode_false_go_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAMPLE_MODE", "false")
    monkeypatch.setenv("ZETARIS_API_KEY", "zk_live_example")
    monkeypatch.setenv("METERLESS_RUNTIME_TOKEN", "rt_live_example")
    s = Settings()
    assert s.effective_sample_mode(None) is False
    assert s.effective_sample_mode(True) is True        # a request can still ask for sample mode
