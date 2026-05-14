from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Id = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{1,62}$")]
CloudProvider = Literal["aws", "azure", "gcp"]
DeploymentEnvironment = Literal["dev", "staging", "prod"]


class StrictBase(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class BoundingBox(StrictBase):
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)


class Evidence(StrictBase):
    source_element_id: str
    label: str = Field(min_length=1, max_length=200)
    confidence: float = Field(ge=0, le=1)
    bounds: BoundingBox | None = None


class TopologyMetadata(StrictBase):
    name: str = Field(min_length=2, max_length=80)
    owner: str = Field(min_length=3, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    tags: dict[str, str] = Field(default_factory=dict)


class DeploymentTarget(StrictBase):
    provider: CloudProvider = "aws"
    region: str = Field(default="us-east-1", pattern=r"^[a-z][a-z0-9-]{1,40}$")
    environment: DeploymentEnvironment = "dev"


class TrustZone(StrictBase):
    id: Id
    name: str = Field(min_length=2, max_length=80)
    exposure: Literal["private", "public", "external"] = "private"


class Port(StrictBase):
    name: str = Field(default="http", min_length=2, max_length=30)
    port: int = Field(ge=1, le=65535)
    protocol: Literal["tcp", "udp"] = "tcp"


class Resources(StrictBase):
    cpu_millicores: int = Field(default=256, ge=128, le=8192)
    memory_mib: int = Field(default=512, ge=128, le=32768)


class ServiceSecurity(StrictBase):
    public: bool = False
    require_auth: bool = True
    tls_required: bool = True
    run_as_non_root: bool = True
    read_only_root_fs: bool = True
    egress: Literal["none", "private", "internet"] = "private"


class ServiceNode(StrictBase):
    id: Id
    name: str = Field(min_length=2, max_length=80)
    kind: Literal["api", "worker", "frontend", "gateway", "cron"] = "api"
    runtime: Literal["python-fastapi", "node", "go", "container"] = "python-fastapi"
    image: str = Field(min_length=3, max_length=250)
    replicas: int = Field(default=2, ge=1, le=50)
    ports: list[Port] = Field(default_factory=list, max_length=16)
    env: dict[str, str] = Field(default_factory=dict)
    resources: Resources = Field(default_factory=Resources)
    security: ServiceSecurity = Field(default_factory=ServiceSecurity)
    trust_zone: Id = "private"
    evidence: Evidence | None = None

    @field_validator("env")
    @classmethod
    def validate_env_keys(cls, env: dict[str, str]) -> dict[str, str]:
        for key in env:
            if not key.isupper() or not key.replace("_", "").isalnum():
                raise ValueError(f"environment variable {key!r} must be SCREAMING_SNAKE_CASE")
        return env


class DataStore(StrictBase):
    id: Id
    name: str = Field(min_length=2, max_length=80)
    kind: Literal["postgres", "mysql", "redis", "s3", "queue"]
    version: str | None = Field(default=None, max_length=40)
    encrypted_at_rest: bool = True
    backups_enabled: bool = True
    public_access: bool = False
    trust_zone: Id = "private"
    evidence: Evidence | None = None


class ExternalSystem(StrictBase):
    id: Id
    name: str = Field(min_length=2, max_length=80)
    trusted: bool = False
    trust_zone: Id = "external"
    evidence: Evidence | None = None


class Edge(StrictBase):
    id: Id
    from_node: Id = Field(alias="from")
    to_node: Id = Field(alias="to")
    protocol: Literal["https", "http", "grpc", "tcp", "postgres", "mysql", "redis", "s3", "sqs"]
    purpose: str = Field(min_length=2, max_length=160)
    encrypted: bool = True
    auth_required: bool = True
    evidence: Evidence | None = None


class TopologySpec(StrictBase):
    schema_version: Literal["w2p.topology.v1"] = "w2p.topology.v1"
    metadata: TopologyMetadata
    deployment: DeploymentTarget = Field(default_factory=DeploymentTarget)
    trust_zones: list[TrustZone] = Field(min_length=1)
    services: list[ServiceNode] = Field(min_length=1)
    datastores: list[DataStore] = Field(default_factory=list)
    external_systems: list[ExternalSystem] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_graph(self) -> TopologySpec:
        zone_ids = {zone.id for zone in self.trust_zones}
        if len(zone_ids) != len(self.trust_zones):
            raise ValueError("trust zone ids must be unique")

        node_ids: set[str] = set()

        for node in [*self.services, *self.datastores, *self.external_systems]:
            if node.id in node_ids:
                raise ValueError(f"duplicate node id {node.id!r}")
            node_ids.add(node.id)
            if node.trust_zone not in zone_ids:
                raise ValueError(f"node {node.id!r} references unknown trust zone {node.trust_zone!r}")

        edge_ids: set[str] = set()
        for edge in self.edges:
            if edge.id in edge_ids:
                raise ValueError(f"duplicate edge id {edge.id!r}")
            edge_ids.add(edge.id)
            if edge.from_node not in node_ids:
                raise ValueError(f"edge {edge.id!r} has unknown source {edge.from_node!r}")
            if edge.to_node not in node_ids:
                raise ValueError(f"edge {edge.id!r} has unknown target {edge.to_node!r}")

        return self


class VisualElement(StrictBase):
    id: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=160)
    element_type: Literal["service", "datastore", "external"]
    subtype: str | None = Field(default=None, max_length=80)
    bounds: BoundingBox
    properties: dict[str, str] = Field(default_factory=dict)


class VisualConnector(StrictBase):
    id: str = Field(min_length=1, max_length=120)
    source_element_id: str = Field(min_length=1, max_length=120)
    target_element_id: str = Field(min_length=1, max_length=120)
    label: str | None = Field(default=None, max_length=160)
    properties: dict[str, str] = Field(default_factory=dict)


class VisualDiagram(StrictBase):
    schema_version: Literal["w2p.visual.v1"] = "w2p.visual.v1"
    name: str = Field(min_length=2, max_length=80)
    owner: str = Field(min_length=3, max_length=120)
    environment: DeploymentEnvironment = "dev"
    provider: CloudProvider = "aws"
    region: str = Field(default="us-east-1", pattern=r"^[a-z][a-z0-9-]{1,40}$")
    elements: list[VisualElement] = Field(min_length=1)
    connectors: list[VisualConnector] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_diagram(self) -> VisualDiagram:
        element_ids = {element.id for element in self.elements}
        if len(element_ids) != len(self.elements):
            raise ValueError("visual element ids must be unique")

        connector_ids: set[str] = set()
        for connector in self.connectors:
            if connector.id in connector_ids:
                raise ValueError(f"duplicate connector id {connector.id!r}")
            connector_ids.add(connector.id)
            if connector.source_element_id not in element_ids:
                raise ValueError(f"connector {connector.id!r} references an unknown source element")
            if connector.target_element_id not in element_ids:
                raise ValueError(f"connector {connector.id!r} references an unknown target element")

        return self


class PolicyIssue(StrictBase):
    severity: Literal["error", "warning"]
    code: str
    message: str
    target: str


class GeneratedFile(StrictBase):
    path: str = Field(min_length=1, max_length=240)
    content: str


class CompileRequest(StrictBase):
    topology: TopologySpec


class CompileResponse(StrictBase):
    status: Literal["success", "policy_failed"]
    topology_hash: str
    policy_issues: list[PolicyIssue]
    generated_files: list[GeneratedFile]


def topology_json_schema() -> dict[str, Any]:
    return TopologySpec.model_json_schema()


def visual_json_schema() -> dict[str, Any]:
    return VisualDiagram.model_json_schema()
