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
    "Do not invent figures. Keep to the structure asked for. British spelling. No markdown headings."
)


class WriterAgent(Agent):
    name = "Writer"
    role = "Drafts briefings and letters from the evidence table (NVIDIA Nemotron via Meterless Nightshift; deterministic template in sample mode)"

    def draft(self, kind: str, instruction: str, evidence_lines: list[str], template_text: str, retry: int = 0) -> dict[str, Any]:
        evidence = "\n".join(f"- {line}" for line in evidence_lines)
        if self.ctx.sample_mode:
            out = self.ctx.model.complete(SYSTEM, template_text)
            self.trace("draft", f"{kind}: {instruction[:120]} ({len(evidence_lines)} evidence lines)",
                       f"{len(out.text)} chars via deterministic template", target_agent="Critic", model=out.model, confidence=1.0, retry_count=retry)
            return {"text": out.text, "model": out.model, "receipt_id": None, "provider": None, "mode": "sample"}
        prompt = f"TASK: {instruction}\n\nEVIDENCE:\n{evidence}\n\nWrite the {kind} now."
        if retry:
            prompt += "\n\nYour previous draft used numbers that are not in the evidence. Use only the evidence numbers."
        try:
            out = self.ctx.model.complete(SYSTEM, prompt, max_tokens=900)
        except ModelError as e:
            self.trace("draft", kind, f"model error: {e}; falling back to the template", model=self.ctx.model.badge, status="error", retry_count=retry)
            return {"text": template_text, "model": "template-fallback", "receipt_id": None, "provider": None, "mode": "fallback"}
        self.trace("draft", f"{kind}: {instruction[:120]} ({len(evidence_lines)} evidence lines)",
                   f"{len(out.text)} chars", target_agent="Critic", model=out.model, confidence=0.8, retry_count=retry,
                   receipt_id=out.receipt_id, provider=out.provider, usage=out.usage)
        return {"text": out.text, "model": out.model, "receipt_id": out.receipt_id, "provider": out.provider, "mode": "live"}
