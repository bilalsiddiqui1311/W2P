from __future__ import annotations

import shutil
import subprocess
import tempfile
import os
from pathlib import Path

from .app_models import TerraformValidationResult, ToolCheck, ValidationFinding


def validate_terraform_files(files: dict[str, str]) -> TerraformValidationResult:
    terraform_files = {
        path.removeprefix("terraform/"): content
        for path, content in files.items()
        if path.startswith("terraform/") and (path.endswith(".tf") or path.endswith(".tfvars") or path.endswith(".tfvars.example"))
    }
    findings = _architecture_findings(terraform_files)
    tool_checks: list[ToolCheck] = []

    if not terraform_files:
        findings.append(
            ValidationFinding(
                severity="error",
                code="W2P-TF-000",
                message="No Terraform files were provided for validation.",
                target="terraform",
            )
        )
        return TerraformValidationResult(status="failed", findings=findings, tool_checks=tool_checks)

    with tempfile.TemporaryDirectory(prefix="w2p-tf-") as temp:
        root = Path(temp)
        for relative_path, content in terraform_files.items():
            destination = root / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content)

        tool_checks.extend(_terraform_checks(root))
        tool_checks.extend(_tflint_checks(root))

    failed = any(finding.severity == "error" for finding in findings) or any(check.status == "failed" for check in tool_checks)
    skipped = tool_checks and all(check.status == "skipped" for check in tool_checks)
    return TerraformValidationResult(
        status="failed" if failed else "skipped" if skipped else "passed",
        findings=findings,
        tool_checks=tool_checks,
    )


def _architecture_findings(files: dict[str, str]) -> list[ValidationFinding]:
    body = "\n".join(files.values())
    findings: list[ValidationFinding] = []

    provider = _detect_provider(body)
    required_markers = _required_markers_for(provider)
    for marker, code in required_markers.items():
        if marker not in body:
            findings.append(
                ValidationFinding(
                    severity="warning",
                    code=code,
                    message=f"Expected Terraform marker was not found: {marker}",
                    target="terraform/main.tf",
                )
            )

    banned_patterns = {
        "assign_public_ip = true": ("error", "W2P-ARCH-101", "ECS services must not assign public IP addresses."),
        "0.0.0.0/0": ("warning", "W2P-ARCH-102", "Open internet CIDR detected; confirm this is explicitly approved."),
        "publicly_accessible       = true": ("error", "W2P-ARCH-103", "Datastores must not be publicly accessible."),
        "storage_encrypted         = false": ("error", "W2P-ARCH-104", "Datastores must be encrypted at rest."),
        'resources = ["*"]': ("warning", "W2P-ARCH-105", "Wildcard IAM resources detected."),
    }
    for pattern, (severity, code, message) in banned_patterns.items():
        if pattern in body:
            findings.append(
                ValidationFinding(
                    severity=severity,
                    code=code,
                    message=message,
                    target="terraform",
                )
            )

    return findings


def _detect_provider(body: str) -> str:
    if 'provider "azurerm"' in body:
        return "azure"
    if 'provider "google"' in body:
        return "gcp"
    return "aws"


def _required_markers_for(provider: str) -> dict[str, str]:
    if provider == "azure":
        return {
            'provider "azurerm"': "W2P-ARCH-AZ-001",
            "azurerm_resource_group": "W2P-ARCH-AZ-002",
            "azurerm_virtual_network": "W2P-ARCH-AZ-003",
            "azurerm_container_app_environment": "W2P-ARCH-AZ-004",
        }
    if provider == "gcp":
        return {
            'provider "google"': "W2P-ARCH-GCP-001",
            "google_compute_network": "W2P-ARCH-GCP-002",
            "google_compute_subnetwork": "W2P-ARCH-GCP-003",
            "google_artifact_registry_repository": "W2P-ARCH-GCP-004",
        }
    return {
        "aws_ecs_task_definition": "W2P-ARCH-001",
        "aws_ecs_service": "W2P-ARCH-002",
        "assign_public_ip = false": "W2P-ARCH-003",
        "storage_encrypted         = true": "W2P-ARCH-004",
    }


def _terraform_checks(root: Path) -> list[ToolCheck]:
    if shutil.which("terraform") is None:
        return [
            ToolCheck(
                tool="terraform",
                status="skipped",
                summary="Terraform CLI is not installed in this environment.",
            )
        ]

    checks = [_run_tool(root, ["terraform", "fmt", "-check", "-recursive"], "terraform fmt")]
    if os.getenv("W2P_TERRAFORM_INIT", "false").lower() != "true":
        checks.append(
            ToolCheck(
                tool="terraform validate",
                status="skipped",
                summary="Provider-backed validation is disabled. Set W2P_TERRAFORM_INIT=true to run terraform init and validate.",
            )
        )
        return checks

    checks.append(_run_tool(root, ["terraform", "init", "-backend=false", "-input=false"], "terraform init"))
    if checks[-1].status != "failed":
        checks.append(_run_tool(root, ["terraform", "validate", "-json"], "terraform validate"))
    return checks


def _tflint_checks(root: Path) -> list[ToolCheck]:
    if shutil.which("tflint") is None:
        return [
            ToolCheck(
                tool="tflint",
                status="skipped",
                summary="tflint is not installed in this environment.",
            )
        ]
    return [_run_tool(root, ["tflint", "--format", "compact"], "tflint")]


def _run_tool(root: Path, command: list[str], label: str) -> ToolCheck:
    try:
        result = subprocess.run(
            command,
            cwd=root,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return ToolCheck(tool=label, status="failed", summary=f"{label} timed out after 60 seconds.")

    output = (result.stdout + "\n" + result.stderr).strip()
    return ToolCheck(
        tool=label,
        status="passed" if result.returncode == 0 else "failed",
        summary=f"{label} exited with code {result.returncode}.",
        output=output[:4000] or None,
    )
