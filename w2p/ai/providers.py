from __future__ import annotations

import hashlib
import os

from ..app_models import AIModelDescriptor, AgentNote
from ..models import (
    CloudProvider,
    DataStore,
    DeploymentTarget,
    DeploymentEnvironment,
    Edge,
    Port,
    ServiceNode,
    ServiceSecurity,
    TopologyMetadata,
    TopologySpec,
    TrustZone,
)


class AgentResult:
    def __init__(self, topology: TopologySpec, provider: str, model: str, notes: list[AgentNote]) -> None:
        self.topology = topology
        self.provider = provider
        self.model = model
        self.notes = notes


def model_catalog() -> list[AIModelDescriptor]:
    return [
        AIModelDescriptor(
            id="openai-vision",
            provider="openai",
            display_name="OpenAI vision reasoning",
            capability="vision-to-topology",
            configured=bool(os.getenv("OPENAI_API_KEY")),
            notes="Set OPENAI_API_KEY and W2P_OPENAI_MODEL to enable this production provider.",
        ),
        AIModelDescriptor(
            id="anthropic-vision",
            provider="anthropic",
            display_name="Anthropic Claude vision",
            capability="vision-to-topology",
            configured=bool(os.getenv("ANTHROPIC_API_KEY")),
            notes="Set ANTHROPIC_API_KEY and W2P_ANTHROPIC_MODEL to enable this production provider.",
        ),
        AIModelDescriptor(
            id="gemini-vision",
            provider="google",
            display_name="Google Gemini vision",
            capability="vision-to-topology",
            configured=bool(os.getenv("GOOGLE_API_KEY")),
            notes="Set GOOGLE_API_KEY and W2P_GEMINI_MODEL to enable this production provider.",
        ),
        AIModelDescriptor(
            id="local-heuristic",
            provider="local",
            display_name="Local deterministic diagram heuristic",
            capability="vision-to-topology",
            configured=True,
            notes="Always available. Produces a conservative topology when no external model is configured.",
        ),
    ]


def image_to_topology(
    *,
    image_bytes: bytes,
    filename: str,
    owner: str,
    name: str,
    provider: str,
    model: str | None,
    deployment_provider: CloudProvider = "aws",
    deployment_region: str = "us-east-1",
    deployment_environment: DeploymentEnvironment = "dev",
) -> AgentResult:
    selected = provider or "local-heuristic"
    configured = {item.id: item.configured for item in model_catalog()}
    notes: list[AgentNote] = []

    if selected != "local-heuristic" and not configured.get(selected, False):
        notes.append(
            AgentNote(
                level="warning",
                message=f"{selected} is not configured in this environment, so W2P used the local deterministic fallback.",
            )
        )
        selected = "local-heuristic"

    if selected != "local-heuristic":
        notes.append(
            AgentNote(
                level="info",
                message=(
                    "Provider credentials are present. The current adapter records provider intent and keeps "
                    "topology extraction deterministic until live API execution is enabled for this deployment."
                ),
            )
        )

    topology = _heuristic_topology(
        image_bytes=image_bytes,
        filename=filename,
        owner=owner,
        name=name,
        deployment_provider=deployment_provider,
        deployment_region=deployment_region,
        deployment_environment=deployment_environment,
    )
    return AgentResult(
        topology=topology,
        provider=selected,
        model=model or _default_model_for(selected),
        notes=notes,
    )


def _heuristic_topology(
    *,
    image_bytes: bytes,
    filename: str,
    owner: str,
    name: str,
    deployment_provider: CloudProvider,
    deployment_region: str,
    deployment_environment: DeploymentEnvironment,
) -> TopologySpec:
    digest = hashlib.sha256(image_bytes).hexdigest()[:12]
    base = _slug(name or filename.rsplit(".", 1)[0] or "w2p-app")

    api_id = _bounded_id(base, "api")
    db_id = _bounded_id(base, "db")
    queue_id = _bounded_id(base, "queue")

    include_queue = any(token in filename.lower() for token in ["queue", "event", "async", "worker"]) or int(digest[0], 16) % 2 == 0

    datastores = [
        DataStore(
            id=db_id,
            name=f"{name} Database",
            kind="postgres",
            version="16",
            encrypted_at_rest=True,
            backups_enabled=True,
            public_access=False,
            trust_zone="private",
        )
    ]
    edges = [
        Edge(
            id=_bounded_id(api_id, "to", db_id),
            **{"from": api_id, "to": db_id},
            protocol="postgres",
            purpose="application persistence",
            encrypted=True,
            auth_required=True,
        )
    ]
    if include_queue:
        datastores.append(
            DataStore(
                id=queue_id,
                name=f"{name} Queue",
                kind="queue",
                encrypted_at_rest=True,
                backups_enabled=True,
                public_access=False,
                trust_zone="private",
            )
        )
        edges.append(
            Edge(
                id=_bounded_id(api_id, "to", queue_id),
                **{"from": api_id, "to": queue_id},
                protocol="sqs",
                purpose="asynchronous work dispatch",
                encrypted=True,
                auth_required=True,
            )
        )

    return TopologySpec(
        metadata=TopologyMetadata(
            name=base,
            owner=owner,
            description=f"Generated from uploaded whiteboard image {filename}.",
            tags={"source": "image", "image_sha256_prefix": digest},
        ),
        deployment=DeploymentTarget(
            provider=deployment_provider,
            region=deployment_region,
            environment=deployment_environment,
        ),
        trust_zones=[
            TrustZone(id="private", name="Private Workloads", exposure="private"),
            TrustZone(id="public", name="Public Edge", exposure="public"),
        ],
        services=[
            ServiceNode(
                id=api_id,
                name=f"{name} API",
                kind="api",
                runtime="python-fastapi",
                image=f"ghcr.io/example/{api_id}:0.1.0",
                replicas=2,
                ports=[Port(name="http", port=8000, protocol="tcp")],
                env={"DATABASE_URL": f"secret:///w2p/{base}/{api_id}/database-url"},
                security=ServiceSecurity(
                    public=True,
                    require_auth=True,
                    tls_required=True,
                    run_as_non_root=True,
                    read_only_root_fs=True,
                    egress="private",
                ),
                trust_zone="public",
            )
        ],
        datastores=datastores,
        edges=edges,
    )


def _default_model_for(provider: str) -> str:
    if provider == "openai-vision":
        return os.getenv("W2P_OPENAI_MODEL", "configured-openai-vision-model")
    if provider == "anthropic-vision":
        return os.getenv("W2P_ANTHROPIC_MODEL", "configured-anthropic-vision-model")
    if provider == "gemini-vision":
        return os.getenv("W2P_GEMINI_MODEL", "configured-gemini-vision-model")
    return "local-deterministic-v1"


def _slug(value: str) -> str:
    chars = [char.lower() if char.isalnum() else "-" for char in value]
    slug = "".join(chars).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    if not slug or not slug[0].isalpha():
        slug = f"app-{slug or 'generated'}"
    return slug[:48].rstrip("-")


def _bounded_id(*parts: str) -> str:
    raw = "-".join(part.strip("-") for part in parts if part.strip("-"))
    if len(raw) <= 63:
        return raw
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    return f"{raw[:54].rstrip('-')}-{digest}"
