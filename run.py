"""VESTING DAY entry point.

  python run.py                       start the HTTP server on 0.0.0.0:PORT (default 8000)
  python run.py --input FILE.json     run one request (the POST /run body) and print the JSON response
  python run.py --query "..."         run one free-text request with a generated run_id

Set SAMPLE_MODE=true (or leave .env empty) to run with no Zetaris, no Nightshift, no network.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid


def main() -> int:
    parser = argparse.ArgumentParser(description="VESTING DAY")
    parser.add_argument("--input", help="JSON file with the POST /run body")
    parser.add_argument("--query", help="free-text request")
    parser.add_argument("--run-id", help="run id (default: generated)")
    parser.add_argument("--sample", action="store_true", help="force sample mode for this run")
    parser.add_argument("--reset-memory", action="store_true", help="clear H-MEM state and held drafts before running")
    args = parser.parse_args()

    if args.reset_memory:
        from app.config import settings
        import shutil
        if settings.memory_dir.exists():
            shutil.rmtree(settings.memory_dir)
        settings.memory_dir.mkdir(parents=True, exist_ok=True)
        print(f"memory cleared: {settings.memory_dir}", file=sys.stderr)

    if args.input or args.query:
        from app.orchestrator import Orchestrator
        from app.schemas import RunRequest
        if args.input:
            with open(args.input, encoding="utf-8") as fh:
                body = json.load(fh)
        else:
            body = {"run_id": args.run_id or f"cli-{uuid.uuid4().hex[:8]}", "input": {"query": args.query}, "options": {}}
        if args.run_id:
            body["run_id"] = args.run_id
        if args.sample:
            body.setdefault("options", {})["sample_mode"] = True
        result = Orchestrator().run(RunRequest(**body))
        print(json.dumps(result.model_dump(), indent=2, ensure_ascii=False))
        return 0 if result.status == "success" else 1

    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, log_level=os.getenv("LOG_LEVEL", "info").lower())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
