from __future__ import annotations

import re
from collections.abc import Iterable

from .models import (
    DataStore,
    DeploymentTarget,
    Edge,
    Evidence,
    ExternalSystem,
    Port,
    ServiceNode,
    ServiceSecurity,
    TopologyMetadata,
    TopologySpec,
    TrustZone,
    VisualConnector,
    VisualDiagram,
    VisualElement,
)


def extract_topology(diagram: VisualDiagram) -> TopologySpec:
    elements = sorted(diagram.elements, key=lambda item: item.id)
    connectors = sorted(diagram.connectors, key=lambda item: item.id)
    id_map = _unique_id_map(elements)

    services: list[ServiceNode] = []
    datastores: list[DataStore] = []
    external_systems: list[ExternalSystem] = []

    for element in elements:
        node_id = id_map[element.id]
        evidence = _evidence(element)
        if element.element_type == "service":
            services.append(_service_from_element(element, node_id, evidence))
        elif element.element_type == "datastore":
            datastores.append(_datastore_from_element(element, node_id, evidence))
        else:
            external_systems.append(
                ExternalSystem(
                    id=node_id,
                    name=element.label,
                    trusted=_as_bool(element.properties.get("trusted"), default=False),
                    trust_zone=element.properties.get("trust_zone", "external"),
                    evidence=evidence,
                )
            )

    edge_id_map = _unique_connector_id_map(connectors)
    edges = sorted(
        [_edge_from_connector(connector, id_map, edge_id_map[connector.id]) for connector in connectors],
        key=lambda item: item.id,
    )
    trust_zones = _trust_zones([*services, *datastores, *external_systems])

    return TopologySpec(
        metadata=TopologyMetadata(
            name=diagram.name,
            owner=diagram.owner,
            description="Extracted from normalized visual diagram input.",
            tags={"source": "visual"},
        ),
        deployment=DeploymentTarget(
            provider=diagram.provider,
            region=diagram.region,
            environment=diagram.environment,
        ),
        trust_zones=trust_zones,
        services=services,
        datastores=datastores,
        external_systems=external_systems,
        edges=edges,
    )


def _service_from_element(element: VisualElement, node_id: str, evidence: Evidence) -> ServiceNode:
    service_kind = _service_kind(element)
    public = _as_bool(element.properties.get("public"), default=service_kind in {"frontend", "gateway"})
    port = _as_int(element.properties.get("port"), default=8000)
    ports = [] if service_kind in {"worker", "cron"} else [Port(name="http", port=port)]

    return ServiceNode(
        id=node_id,
        name=element.label,
        kind=service_kind,
        runtime=element.properties.get("runtime", "python-fastapi"),
        image=element.properties.get("image", f"ghcr.io/example/{node_id}:0.1.0"),
        replicas=_as_int(element.properties.get("replicas"), default=2),
        ports=ports,
        env=_prefixed_properties(element.properties, "env."),
        security=ServiceSecurity(
            public=public,
            require_auth=_as_bool(element.properties.get("require_auth"), default=True),
            tls_required=_as_bool(element.properties.get("tls_required"), default=True),
            run_as_non_root=_as_bool(element.properties.get("run_as_non_root"), default=True),
            read_only_root_fs=_as_bool(element.properties.get("read_only_root_fs"), default=True),
            egress=element.properties.get("egress", "private"),
        ),
        trust_zone=element.properties.get("trust_zone", "public" if public else "private"),
        evidence=evidence,
    )


def _datastore_from_element(element: VisualElement, node_id: str, evidence: Evidence) -> DataStore:
    return DataStore(
        id=node_id,
        name=element.label,
        kind=_datastore_kind(element),
        version=element.properties.get("version"),
        encrypted_at_rest=_as_bool(element.properties.get("encrypted_at_rest"), default=True),
        backups_enabled=_as_bool(element.properties.get("backups_enabled"), default=True),
        public_access=_as_bool(element.properties.get("public_access"), default=False),
        trust_zone=element.properties.get("trust_zone", "private"),
        evidence=evidence,
    )


def _edge_from_connector(connector: VisualConnector, id_map: dict[str, str], edge_id: str) -> Edge:
    protocol = connector.properties.get("protocol") or _protocol_from_label(connector.label)
    encrypted = protocol not in {"http", "tcp"} or _as_bool(connector.properties.get("encrypted"), default=False)

    return Edge(
        id=edge_id,
        from_node=id_map[connector.source_element_id],
        to_node=id_map[connector.target_element_id],
        protocol=protocol,
        purpose=connector.label or "service dependency",
        encrypted=encrypted,
        auth_required=_as_bool(connector.properties.get("auth_required"), default=True),
        evidence=Evidence(
            source_element_id=connector.id,
            label=connector.label or connector.id,
            confidence=0.85,
            bounds=None,
        ),
    )


def _trust_zones(nodes: Iterable[ServiceNode | DataStore | ExternalSystem]) -> list[TrustZone]:
    exposures = {
        "private": "private",
        "public": "public",
        "external": "external",
    }
    zone_ids = sorted({node.trust_zone for node in nodes})
    return [
        TrustZone(id=zone_id, name=zone_id.replace("-", " ").title(), exposure=exposures.get(zone_id, "private"))
        for zone_id in zone_ids
    ]


def _stable_id(label: str, fallback: str) -> str:
    candidate = re.sub(r"[^a-z0-9-]+", "-", label.lower()).strip("-")
    candidate = re.sub(r"-+", "-", candidate)
    if not candidate or not candidate[0].isalpha():
        candidate = f"node-{fallback.lower()}"
    if len(candidate) == 1:
        candidate = f"{candidate}-node"
    return candidate[:63].rstrip("-")


def _unique_id_map(elements: list[VisualElement]) -> dict[str, str]:
    seen: dict[str, int] = {}
    id_map: dict[str, str] = {}
    for element in elements:
        base = _stable_id(element.label, element.id)
        index = seen.get(base, 0)
        seen[base] = index + 1
        if index == 0:
            id_map[element.id] = base
            continue

        suffix = f"-{index + 1}"
        id_map[element.id] = f"{base[: 63 - len(suffix)].rstrip('-')}{suffix}"
    return id_map


def _unique_connector_id_map(connectors: list[VisualConnector]) -> dict[str, str]:
    seen: dict[str, int] = {}
    id_map: dict[str, str] = {}
    for connector in connectors:
        base = _stable_id(connector.label or connector.id, connector.id)
        index = seen.get(base, 0)
        seen[base] = index + 1
        if index == 0:
            id_map[connector.id] = base
            continue

        suffix = f"-{index + 1}"
        id_map[connector.id] = f"{base[: 63 - len(suffix)].rstrip('-')}{suffix}"
    return id_map


def _service_kind(element: VisualElement) -> str:
    value = (element.subtype or element.properties.get("kind") or element.label).lower()
    if "worker" in value:
        return "worker"
    if "cron" in value or "schedule" in value:
        return "cron"
    if "front" in value or "web" in value:
        return "frontend"
    if "gateway" in value or "edge" in value:
        return "gateway"
    return "api"


def _datastore_kind(element: VisualElement) -> str:
    value = (element.subtype or element.properties.get("kind") or element.label).lower()
    if "mysql" in value:
        return "mysql"
    if "redis" in value or "cache" in value:
        return "redis"
    if "bucket" in value or "object" in value or "s3" in value:
        return "s3"
    if "queue" in value or "sqs" in value:
        return "queue"
    return "postgres"


def _protocol_from_label(label: str | None) -> str:
    value = (label or "").lower()
    if "postgres" in value or "sql" in value:
        return "postgres"
    if "mysql" in value:
        return "mysql"
    if "redis" in value:
        return "redis"
    if "s3" in value or "object" in value:
        return "s3"
    if "queue" in value or "sqs" in value:
        return "sqs"
    if "grpc" in value:
        return "grpc"
    if "http://" in value or value == "http":
        return "http"
    return "https"


def _evidence(element: VisualElement) -> Evidence:
    return Evidence(
        source_element_id=element.id,
        label=element.label,
        confidence=_as_float(element.properties.get("confidence"), default=0.9),
        bounds=element.bounds,
    )


def _prefixed_properties(properties: dict[str, str], prefix: str) -> dict[str, str]:
    return {
        key.removeprefix(prefix).upper(): value
        for key, value in sorted(properties.items())
        if key.startswith(prefix)
    }


def _as_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "y"}


def _as_int(value: str | None, *, default: int) -> int:
    if value is None:
        return default
    return int(value)


def _as_float(value: str | None, *, default: float) -> float:
    if value is None:
        return default
    return float(value)
