"""JSONL agent traces - the evidence of real agent work.

One file per run: logs/trace-<run_id>.jsonl. One JSON object per line with the
HackOS fields: timestamp, run_id, agent_name, action, input_summary,
output_summary, target_agent, model, confidence, retry_count, status.
Lines are also echoed to the console (stderr, so the CLI's JSON on stdout stays clean). Traces are only ever written by the agents
as they run, never by hand.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Tracer:
    def __init__(self, run_id: str, logs_dir: Path, echo: bool = True) -> None:
        self.run_id = run_id
        self.trace_id = f"trace-{run_id}"
        logs_dir.mkdir(parents=True, exist_ok=True)
        self.path = logs_dir / f"{self.trace_id}.jsonl"
        self._fh = open(self.path, "w", encoding="utf-8")
        self._echo = echo
        self.events: list[dict[str, Any]] = []

    @property
    def log_file(self) -> str:
        # relative to the repo root, as in the guide's example
        return f"logs/{self.path.name}"

    def log(
        self,
        agent_name: str,
        action: str,
        input_summary: str,
        output_summary: str,
        target_agent: Optional[str] = None,
        model: Optional[str] = None,
        confidence: Optional[float] = None,
        retry_count: int = 0,
        status: str = "success",
        **extra: Any,
    ) -> dict[str, Any]:
        event: dict[str, Any] = {
            "timestamp": _now_iso(),
            "run_id": self.run_id,
            "agent_name": agent_name,
            "action": action,
            "input_summary": _clip(input_summary),
            "output_summary": _clip(output_summary),
            "target_agent": target_agent,
            "model": model,
            "confidence": confidence,
            "retry_count": retry_count,
            "status": status,
        }
        if extra:
            event["details"] = extra
        line = json.dumps(event, ensure_ascii=False)
        self._fh.write(line + "\n")
        self._fh.flush()
        if self._echo:
            try:
                print(line, file=sys.stderr, flush=True)
            except (BrokenPipeError, OSError):
                pass
        self.events.append(event)
        return event

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass


def _clip(s: str, n: int = 400) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 3] + "..."
