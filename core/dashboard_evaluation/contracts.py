from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ExpectedDashboardElement(BaseModel):
    element_id: str
    label: str
    acceptable_slot_ids: list[str] = Field(default_factory=list)
    acceptable_block_types: list[str] = Field(default_factory=list)
    required: bool = True


class DashboardEvaluationCase(BaseModel):
    case_id: str
    question: str
    audience_id: Literal["practitioner", "executive", "management", "external"]
    purpose_id: Literal["current_status", "issue_response", "future_business", "root_cause"]
    expected_elements: list[ExpectedDashboardElement] = Field(default_factory=list)


class DashboardEvaluationCheck(BaseModel):
    check_id: str
    label: str
    status: Literal["pass", "fail", "manual_review", "not_applicable"]
    score: float | None = None
    detail: str


class DashboardEvaluationResult(BaseModel):
    case_id: str
    request_id: str
    question: str
    audience_id: str
    purpose_id: str
    delivered_block_types: list[str] = Field(default_factory=list)
    checks: list[DashboardEvaluationCheck] = Field(default_factory=list)
    passed_count: int = 0
    failed_count: int = 0
    manual_review_count: int = 0
    not_applicable_count: int = 0
