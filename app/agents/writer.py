"""WriterAgent: turns computed evidence into a short briefing or draft.

Live mode: NVIDIA Nemotron via Meterless Nightshift, with the evidence table
in the prompt and an instruction to use only those numbers. Sample mode: a
deterministic template over the same evidence, badged "sample-mode/template".
Either way the model badge, receipt id and the evidence ids travel with the text.
"""

from __future__ import annotations

from typing import Any

from app.adapters.nightshift import ModelError
from app.agents.base import Agent

SYSTEM = (
    "You write short, plain-English briefings for the finance lead of a merging English council "
    "(West Surrey, vesting day 1 April 2027). Use only the numbers and names in the EVIDENCE block. "
    "Do not invent figures. Keep to the structure asked for. British spelling. No markdown headings. "
    "Never claim more than the evidence states: a supplier pair is 'shared' only when the evidence says so, "
    "and 'confirmed' only when the evidence says a human confirmed it; a model's opinion is a suggestion "
    "awaiting a human decision, and say so. Where the evidence marks data as SYNTHETIC, say SYNTHETIC."
)


class WriterAgent(Agent):
    name = "Writer"
    role = "Drafts briefings and letters from the evidence table (NVIDIA Nemotron via Meterless Nightshift; deterministic template in sample mode)"

    def draft(self, kind: str, instruction: str, evidence_lines: list[str], template_text: str, retry: int = 0,
              reasons: list[str] | None = None) -> dict[str, Any]:
        evidence = "\n".join(f"- {line}" for line in evidence_lines)
        if self.ctx.sample_mode:
            out = self.ctx.model.complete(SYSTEM, template_text)
            self.trace("draft", f"{kind}: {instruction[:120]} ({len(evidence_lines)} evidence lines)",
                       f"{len(out.text)} chars via deterministic template", target_agent="Critic", model=out.model, confidence=1.0, retry_count=retry)
            return {"text": out.text, "model": out.model, "receipt_id": None, "provider": None, "mode": "sample"}
        prompt = f"TASK: {instruction}\n\nEVIDENCE:\n{evidence}\n\nWrite the {kind} now."
        if retry:
            why = "; ".join(reasons) if reasons else "it used numbers that are not in the evidence"
            prompt += f"\n\nYour previous draft was rejected by the Critic: {why}. Fix exactly that, using only the evidence."
        try:
            out = self.ctx.model.complete(SYSTEM, prompt, max_tokens=900)
        except ModelError as e:
            self.trace("draft", kind, f"model error: {e}; falling back to the template", model=self.ctx.model.badge, status="error", retry_count=retry)
            return {"text": template_text, "model": "template-fallback", "receipt_id": None, "provider": None, "mode": "fallback"}
        self.trace("draft", f"{kind}: {instruction[:120]} ({len(evidence_lines)} evidence lines)",
                   f"{len(out.text)} chars", target_agent="Critic", model=out.model, confidence=0.8, retry_count=retry,
                   receipt_id=out.receipt_id, provider=out.provider, usage=out.usage)
        return {"text": out.text, "model": out.model, "receipt_id": out.receipt_id, "provider": out.provider, "mode": "live"}

    def fallback(self, kind: str, template_text: str, reasons: list[str]) -> dict[str, Any]:
        """The Critic rejected the model twice: ship the deterministic template instead, and say so."""
        self.trace("draft", f"{kind}: template fallback", f"model drafts rejected twice ({'; '.join(reasons)[:200]}); using the evidence-only template",
                   target_agent="Critic", model="template-fallback", confidence=1.0, retry_count=2, status="fallback")
        return {"text": template_text, "model": "template-fallback", "receipt_id": None, "provider": None, "mode": "fallback"}
