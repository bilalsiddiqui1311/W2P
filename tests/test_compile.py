from __future__ import annotations

from pathlib import Path

from w2p.compiler import compile_topology, files_as_mapping
from w2p.models import TopologySpec


def test_compile_includes_required_output_groups() -> None:
    topology = TopologySpec.model_validate_json(Path("examples/topology.json").read_text())

    response = compile_topology(topology)
    files = files_as_mapping(response)

    assert response.status == "success"
    assert "terraform/main.tf" in files
    assert "backend/app/main.py" in files
    assert "container/Dockerfile" in files
    assert "policy/topology.rego" in files
    assert "schema/topology.schema.json" in files
    assert "FastAPI" in files["backend/app/main.py"]
    assert "aws_ecs_cluster" in files["terraform/main.tf"]


def test_policy_failure_is_reported_with_generated_files() -> None:
    data = TopologySpec.model_validate_json(Path("examples/topology.json").read_text()).model_dump(
        mode="python",
        by_alias=True,
    )
    data["services"][0]["image"] = "ghcr.io/example/payments-api:latest"

    response = compile_topology(TopologySpec.model_validate(data))
    files = files_as_mapping(response)

    assert response.status == "policy_failed"
    assert any(issue.code == "W2P-SVC-001" for issue in response.policy_issues)
    assert "terraform/main.tf" in files


def test_compile_generates_provider_matched_terraform() -> None:
    data = TopologySpec.model_validate_json(Path("examples/topology.json").read_text()).model_dump(
        mode="python",
        by_alias=True,
    )
    data["deployment"] = {
        "provider": "gcp",
        "region": "us-central1",
        "environment": "staging",
    }

    response = compile_topology(TopologySpec.model_validate(data))
    files = files_as_mapping(response)

    assert response.status == "success"
    assert 'provider "google"' in files["terraform/versions.tf"]
    assert "google_compute_network" in files["terraform/main.tf"]
