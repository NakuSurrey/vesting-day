"""Shared run context and the agent base class.

Each agent is a distinct code path with one responsibility. They hand work to
each other through return values, and every step they take is written to the
run's JSONL trace by the tracer, as it happens.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.adapters.companies_house import CompaniesHouseClient
from app.adapters.datalayer import DataLayer
from app.adapters.nightshift import ModelClient
from app.config import Settings
from app.engines.hmem import HMEM
from app.trace import Tracer


class UnsupportedRequest(Exception):
    """Raised by the Router when a free-text request matches none of the flows."""


@dataclass
class RunContext:
    run_id: str
    tracer: Tracer
    settings: Settings
    sample_mode: bool
    data: DataLayer
    model: ModelClient
    memory: HMEM
    companies_house: CompaniesHouseClient
    approvals: Any
    query: str
    councils: list[str]
    params: dict[str, Any] = field(default_factory=dict)
    agents_used: dict[str, str] = field(default_factory=dict)  # name -> role, in order of first use


class Agent:
    name = "Agent"
    role = ""

    def __init__(self, ctx: RunContext) -> None:
        self.ctx = ctx
        ctx.agents_used.setdefault(self.name, self.role)

    def trace(
        self,
        action: str,
        input_summary: str,
        output_summary: str,
        target_agent: Optional[str] = None,
        model: Optional[str] = None,
        confidence: Optional[float] = None,
        retry_count: int = 0,
        status: str = "success",
        **details: Any,
    ) -> None:
        self.ctx.tracer.log(
            agent_name=self.name,
            action=action,
            input_summary=input_summary,
            output_summary=output_summary,
            target_agent=target_agent,
            model=model,
            confidence=confidence,
            retry_count=retry_count,
            status=status,
            **details,
        )
