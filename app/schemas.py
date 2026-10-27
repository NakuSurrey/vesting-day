"""Request and response shapes for POST /run.

One JSON request in, one JSON response out, so the agent can be driven with curl
as easily as from the web page.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class RunInput(BaseModel):
    query: str = Field(..., description="Free text request, e.g. 'Which suppliers do Woking and Guildford share?'")
    councils: Optional[list[str]] = Field(default=None, description="Optional subset of Woking, Guildford, Waverley")
    params: dict[str, Any] = Field(default_factory=dict, description="Optional flow parameters")


class RunOptions(BaseModel):
    sample_mode: Optional[bool] = Field(default=None, description="Force sample mode for this run")


class RunRequest(BaseModel):
    run_id: str = Field(..., description="Caller-supplied id; traces are written to logs/trace-<run_id>.jsonl")
    input: RunInput
    options: RunOptions = Field(default_factory=RunOptions)


class AgentInfo(BaseModel):
    name: str
    role: str


class RunOutput(BaseModel):
    summary: str
    recommendations: list[str] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)


class RunSuccess(BaseModel):
    run_id: str
    status: str = "success"
    output: RunOutput
    agents: list[AgentInfo]
    trace_id: str
    log_file: str
    execution_time_seconds: float


class RunErrorDetail(BaseModel):
    type: str
    message: str
    recoverable: bool


class RunError(BaseModel):
    run_id: str
    status: str = "error"
    error: RunErrorDetail
    trace_id: str
    execution_time_seconds: float
