"""Orchestrator: wires one request through the agents and returns the HackOS response shape.

Mode is decided once per run (sample or live), the adapters are built to match,
and the Router picks the flow. H-MEM and the approval store persist across runs
so a human decision made in one request changes the answer to the next.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from app.adapters.companies_house import CompaniesHouseClient
from app.adapters.datalayer import DataLayerError, LocalDataLayer, ZetarisDataLayer
from app.adapters.nightshift import ModelError, NightshiftClient, TemplateModel
from app.agents.approval import ApprovalStore
from app.agents.base import RunContext, UnsupportedRequest
from app.agents.router import RouterAgent
from app.config import Settings, settings as default_settings
from app.engines.hmem import HMEM
from app.flows import approve_draft, confirm_match, contract_cliff, policy_gap, supplier_overlap
from app.schemas import AgentInfo, RunError, RunErrorDetail, RunOutput, RunRequest, RunSuccess
from app.trace import Tracer

FLOW_RUNNERS = {
    "supplier_overlap": supplier_overlap.run,
    "confirm_match": confirm_match.run,
    "contract_cliff": contract_cliff.run,
    "policy_gap": policy_gap.run,
    "approve_draft": approve_draft.run,
}


class Orchestrator:
    def __init__(self, cfg: Settings | None = None) -> None:
        self.cfg = cfg or default_settings
        self.cfg.memory_dir.mkdir(parents=True, exist_ok=True)
        self.cfg.logs_dir.mkdir(parents=True, exist_ok=True)
        self.memory = HMEM(persist_dir=str(self.cfg.memory_dir), actor="vesting-day")
        self.approvals = ApprovalStore(self.cfg.memory_dir / "approvals.json")
        self.sources = self._load_sources()
        self._local_layer: LocalDataLayer | None = None

    def _load_sources(self) -> dict[str, Any]:
        p = self.cfg.data_dir / "sources.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    def _data_layer(self, sample: bool):
        if sample:
            if self._local_layer is None:
                self._local_layer = LocalDataLayer(self.cfg.data_dir)
            return self._local_layer
        return ZetarisDataLayer(self.cfg.zetaris_rest_url, self.cfg.zetaris_org_id, self.cfg.zetaris_api_key,
                                table_prefix=self.cfg.__dict__.get("zetaris_table_prefix", ""))

    def _model(self, sample: bool):
        if sample:
            return TemplateModel()
        return NightshiftClient(self.cfg.meterless_base_url, self.cfg.meterless_runtime_token, self.cfg.meterless_model)

    def run(self, req: RunRequest) -> RunSuccess | RunError:
        t0 = time.time()
        tracer = Tracer(req.run_id, self.cfg.logs_dir)
        sample = self.cfg.effective_sample_mode(req.options.sample_mode)
        ctx = RunContext(
            run_id=req.run_id, tracer=tracer, settings=self.cfg, sample_mode=sample,
            data=self._data_layer(sample), model=self._model(sample), memory=self.memory,
            companies_house=CompaniesHouseClient(self.cfg.companies_house_api_key, self.cfg.data_dir / "companies_house.json", live=not sample),
            approvals=self.approvals, query=req.input.query, councils=list(req.input.councils or []), params=dict(req.input.params or {}),
        )
        tracer.log("Orchestrator", "start", req.input.query, f"mode={'sample' if sample else 'live'}; data layer={ctx.data.name}; model={ctx.model.badge}",
                   target_agent="Router", confidence=1.0, sample_mode=sample)
        try:
            route = RouterAgent(ctx).route(req.input.query, ctx.councils or None, ctx.params)
            ctx.councils = route.councils
            ctx.params = route.params
            result = FLOW_RUNNERS[route.flow](ctx, self.sources)
            result["artifacts"].insert(0, {
                "type": "run_mode", "sample_mode": sample, "flow": route.flow, "router_confidence": route.confidence,
                "data_layer": ctx.data.name, "model": ctx.model.badge,
                "note": "SAMPLE_MODE: cached published council data, deterministic template instead of a model" if sample else "live: Zetaris federation + NVIDIA Nemotron via Meterless Nightshift",
            })
            elapsed = round(time.time() - t0, 2)
            tracer.log("Orchestrator", "finish", route.flow, f"success in {elapsed}s; {len(tracer.events)} trace events", confidence=1.0)
            return RunSuccess(
                run_id=req.run_id, status="success",
                output=RunOutput(summary=result["summary"], recommendations=result["recommendations"], artifacts=result["artifacts"]),
                agents=[AgentInfo(name=n, role=r) for n, r in ctx.agents_used.items()],
                trace_id=tracer.trace_id, log_file=tracer.log_file, execution_time_seconds=elapsed,
            )
        except UnsupportedRequest as e:
            return self._error(req, tracer, t0, "UnsupportedRequest", str(e), recoverable=True)
        except (confirm_match.FlowError, approve_draft.FlowError) as e:
            return self._error(req, tracer, t0, "InvalidInput", str(e), recoverable=True)
        except DataLayerError as e:
            return self._error(req, tracer, t0, e.type_, str(e), recoverable=e.recoverable)
        except ModelError as e:
            return self._error(req, tracer, t0, "ModelError", str(e), recoverable=e.recoverable)
        except Exception as e:  # never crash the judge's curl
            return self._error(req, tracer, t0, type(e).__name__, f"{e}", recoverable=False)
        finally:
            tracer.close()

    def _error(self, req: RunRequest, tracer: Tracer, t0: float, type_: str, message: str, recoverable: bool) -> RunError:
        elapsed = round(time.time() - t0, 2)
        tracer.log("Orchestrator", "error", req.input.query, f"{type_}: {message}", status="error", confidence=None)
        return RunError(run_id=req.run_id, status="error", error=RunErrorDetail(type=type_, message=message, recoverable=recoverable),
                        trace_id=tracer.trace_id, execution_time_seconds=elapsed)
