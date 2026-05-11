from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from .emitters.container import generate_container_files
from .emitters.fastapi_backend import generate_backend_files
from .emitters.terraform import generate_terraform_files
from .models import CompileResponse, GeneratedFile, TopologySpec, topology_json_schema, visual_json_schema
from .policy import REGO_POLICY, evaluate_policies, has_errors


def compile_topology(topology: TopologySpec) -> CompileResponse:
    normalized = normalize_topology(topology)
    policy_issues = evaluate_policies(normalized)

    files: dict[str, str] = {}
    files.update(generate_terraform_files(normalized))
    files.update(generate_backend_files(normalized))
    files.update(generate_container_files(normalized))
    files["policy/topology.rego"] = REGO_POLICY
    files["schema/topology.schema.json"] = json.dumps(topology_json_schema(), indent=2, sort_keys=True) + "\n"
    files["schema/visual.schema.json"] = json.dumps(visual_json_schema(), indent=2, sort_keys=True) + "\n"

    return CompileResponse(
        status="policy_failed" if has_errors(policy_issues) else "success",
        topology_hash=hash_topology(normalized),
        policy_issues=policy_issues,
        generated_files=_generated_files(files),
    )


def normalize_topology(topology: TopologySpec) -> TopologySpec:
    data = topology.model_dump(mode="python", by_alias=True, exclude_none=True)
    data["trust_zones"] = sorted(data["trust_zones"], key=lambda item: item["id"])
    data["services"] = sorted(data["services"], key=lambda item: item["id"])
    data["datastores"] = sorted(data.get("datastores", []), key=lambda item: item["id"])
    data["external_systems"] = sorted(data.get("external_systems", []), key=lambda item: item["id"])
    data["edges"] = sorted(data.get("edges", []), key=lambda item: item["id"])
    return TopologySpec.model_validate(data)


def hash_topology(topology: TopologySpec) -> str:
    canonical = json.dumps(
        topology.model_dump(mode="json", by_alias=True, exclude_none=True),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def files_as_mapping(response: CompileResponse) -> dict[str, str]:
    return {generated.path: generated.content for generated in response.generated_files}


def _generated_files(files: Mapping[str, str]) -> list[GeneratedFile]:
    return [GeneratedFile(path=path, content=content) for path, content in sorted(files.items())]
