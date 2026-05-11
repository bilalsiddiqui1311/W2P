from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import GeneratedFile, PolicyIssue, TopologySpec


class AppBase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class UserProfile(AppBase):
    id: str
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    name: str
    created_at: str


class SignupRequest(AppBase):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    name: str | None = Field(default=None, max_length=120)
    password: str = Field(min_length=8, max_length=200)


class LoginRequest(AppBase):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=1, max_length=200)


class AuthResponse(AppBase):
    token: str
    token_type: Literal["bearer"] = "bearer"
    user: UserProfile


class AIModelDescriptor(AppBase):
    id: str
    provider: str
    display_name: str
    capability: Literal["vision-to-topology", "terraform-review"]
    configured: bool
    notes: str


class AgentNote(AppBase):
    level: Literal["info", "warning"]
    message: str


class ValidationFinding(AppBase):
    severity: Literal["error", "warning", "info"]
    code: str
    message: str
    target: str


class ToolCheck(AppBase):
    tool: str
    status: Literal["passed", "failed", "skipped"]
    summary: str
    output: str | None = None


class TerraformValidationResult(AppBase):
    status: Literal["passed", "failed", "skipped"]
    findings: list[ValidationFinding]
    tool_checks: list[ToolCheck]


class TerraformValidationRequest(AppBase):
    files: list[GeneratedFile] = Field(min_length=1)


class SaveTopologyRequest(AppBase):
    name: str = Field(min_length=2, max_length=120)
    topology: TopologySpec
    provider: str = Field(default="manual", max_length=80)
    model: str = Field(default="manual", max_length=120)


class CodebaseSummary(AppBase):
    id: str
    name: str
    provider: str
    model: str
    status: str
    created_at: str
    updated_at: str


class CodebaseDetail(CodebaseSummary):
    topology: TopologySpec
    topology_hash: str
    policy_issues: list[PolicyIssue]
    validation: TerraformValidationResult
    generated_files: list[GeneratedFile]
    agent_notes: list[AgentNote] = Field(default_factory=list)
