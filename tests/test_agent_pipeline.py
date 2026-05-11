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

