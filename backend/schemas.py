from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class OptimizeRequest(BaseModel):
    plan: dict[str, Any] = Field(default_factory=dict)
    scenario_ids: list[str] = Field(default_factory=lambda: ["BASE", "MANDATORY_STRESS"], min_length=1)
    run_frontier: bool = True


class CalculateRequest(BaseModel):
    plan: dict[str, Any] = Field(default_factory=dict)
    scenario_id: str = Field(default="BASE", min_length=1)


class FrontierRequest(BaseModel):
    plan: dict[str, Any] = Field(default_factory=dict)
    scenario_ids: list[str] = Field(default_factory=lambda: ["BASE", "MANDATORY_STRESS"])
