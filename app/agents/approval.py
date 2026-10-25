"""ApprovalGateAgent: the human-in-the-loop boundary.

Nothing leaves as an action. Drafts are held here with status "pending" until
a person approves or rejects them through a later request, and a supplier
match becomes "confirmed" only when a person says so. Human decisions are
passed to the Memory agent so the system remembers them next time.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.agents.base import Agent


class ApprovalStore:
    """Small JSON file of drafts and decisions, next to the H-MEM state."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.state: dict[str, Any] = {"drafts": {}, "seq": 0}
        if path.exists():
            try:
                self.state = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.state, indent=1, ensure_ascii=False), encoding="utf-8")

    def add_draft(self, draft: dict[str, Any]) -> str:
        self.state["seq"] += 1
        did = f"draft-{self.state['seq']}"
        draft = {**draft, "id": did, "status": "pending", "created_at": datetime.now(timezone.utc).isoformat()}
        self.state["drafts"][did] = draft
        self.save()
        return did

    def get(self, did: str) -> Optional[dict[str, Any]]:
        return self.state["drafts"].get(did)

    def set_status(self, did: str, status: str, actor: str) -> dict[str, Any]:
        d = self.state["drafts"][did]
        d["status"] = status
        d["decided_by"] = actor
        d["decided_at"] = datetime.now(timezone.utc).isoformat()
        self.save()
        return d

    def pending(self) -> list[dict[str, Any]]:
        return [d for d in self.state["drafts"].values() if d["status"] == "pending"]


class ApprovalGateAgent(Agent):
    name = "ApprovalGate"
    role = "Holds every draft for human approval and records human confirmations of supplier matches; no action is ever taken autonomously"

    def hold(self, kind: str, title: str, text: str, model: str, evidence_ids: list[str], receipt_id: Optional[str] = None, recipient: str = "") -> dict[str, Any]:
        did = self.ctx.approvals.add_draft({
            "kind": kind, "title": title, "text": text, "model": model, "receipt_id": receipt_id,
            "evidence_ids": evidence_ids, "recipient": recipient, "run_id": self.ctx.run_id,
        })
        self.trace("hold_for_approval", f"{kind}: {title}", f"{did} pending; nothing sent", confidence=1.0, draft_id=did, model=model)
        return self.ctx.approvals.get(did)

    def decide_draft(self, draft_id: str, decision: str, actor: str = "human") -> dict[str, Any]:
        d = self.ctx.approvals.get(draft_id)
        if not d:
            raise KeyError(f"no draft {draft_id}")
        status = "approved" if decision == "approve" else "rejected"
        d = self.ctx.approvals.set_status(draft_id, status, actor)
        self.trace("decide_draft", f"{draft_id} {decision} by {actor}", f"{draft_id} now {status}; still nothing sent - approval records intent only", confidence=1.0)
        return d

    def confirm_match(self, a_council: str, a_name: str, b_council: str, b_name: str, verdict: str, actor: str = "human") -> dict[str, Any]:
        self.trace("record_human_decision", f"{a_name} ({a_council}) vs {b_name} ({b_council}) -> {verdict}",
                   "human decision accepted; handing to Memory", target_agent="Memory", confidence=1.0)
        return {"a_council": a_council, "a_name": a_name, "b_council": b_council, "b_name": b_name, "verdict": verdict, "actor": actor}
