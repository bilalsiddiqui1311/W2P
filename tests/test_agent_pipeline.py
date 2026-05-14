from __future__ import annotations

from w2p.ai.providers import image_to_topology
from w2p.compiler import compile_topology
from w2p.validation import validate_terraform_files


def test_image_agent_generates_validated_terraform_artifacts() -> None:
    result = image_to_topology(
        image_bytes=b"whiteboard-image",
        filename="checkout.png",
        owner="user@example.com",
        name="checkout-platform",
        provider="local-heuristic",
        model=None,
    )

    compiled = compile_topology(result.topology)
    validation = validate_terraform_files({item.path: item.content for item in compiled.generated_files})

    assert compiled.status == "success"
    assert any(item.path == "terraform/main.tf" for item in compiled.generated_files)
    assert validation.status in {"passed", "skipped"}
    assert not any(finding.severity == "error" for finding in validation.findings)


def test_image_agent_handles_long_names_with_queue_edges() -> None:
    result = image_to_topology(
        image_bytes=b"long-whiteboard-image",
        filename="gemini-generated-image-queue.png",
        owner="user@example.com",
        name="gemini-generated-image-p6yymmp6yymmp6yymmp6yymmp6yy",
        provider="local-heuristic",
        model=None,
    )

    edge_ids = [edge.id for edge in result.topology.edges]
    compiled = compile_topology(result.topology)

    assert len(edge_ids) == len(set(edge_ids))
    assert all(len(edge_id) <= 63 for edge_id in edge_ids)
    assert compiled.status == "success"


def test_image_agent_records_requested_deployment_target() -> None:
    result = image_to_topology(
        image_bytes=b"azure-whiteboard-image",
        filename="architecture.png",
        owner="user@example.com",
        name="checkout-platform",
        provider="local-heuristic",
        model=None,
        deployment_provider="azure",
        deployment_region="eastus",
        deployment_environment="staging",
    )
    compiled = compile_topology(result.topology)

    assert result.topology.deployment.provider == "azure"
    assert result.topology.deployment.region == "eastus"
    assert result.topology.deployment.environment == "staging"
    assert any(item.path == "terraform/main.tf" and "azurerm_resource_group" in item.content for item in compiled.generated_files)
