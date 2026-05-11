from __future__ import annotations

import re

from .models import DataStore, Edge, PolicyIssue, ServiceNode, TopologySpec

SECRET_KEY_PATTERN = re.compile(r"(SECRET|TOKEN|PASSWORD|PRIVATE_KEY|API_KEY|DATABASE_URL)", re.IGNORECASE)

REGO_POLICY = """package w2p.topology

deny[msg] {
  service := input.services[_]
  not regex.match("(:[^/:]+$)|(@sha256:)", service.image)
  msg := sprintf("service %s does not use a pinned image tag or digest", [service.id])
}

deny[msg] {
  service := input.services[_]
  endswith(service.image, ":latest")
  msg := sprintf("service %s uses a mutable latest image tag", [service.id])
}

deny[msg] {
  service := input.services[_]
  service.security.public
  not service.security.require_auth
  msg := sprintf("public service %s does not require authentication", [service.id])
}

deny[msg] {
  service := input.services[_]
  service.security.public
  not service.security.tls_required
  msg := sprintf("public service %s does not require TLS", [service.id])
}

deny[msg] {
  service := input.services[_]
  service.security.public
  count(service.ports) == 0
  msg := sprintf("public service %s does not declare a port", [service.id])
}

deny[msg] {
  datastore := input.datastores[_]
  datastore.public_access
  msg := sprintf("datastore %s allows public access", [datastore.id])
}

deny[msg] {
  edge := input.edges[_]
  edge.protocol == "http"
  msg := sprintf("edge %s uses plaintext HTTP", [edge.id])
}
"""


def evaluate_policies(topology: TopologySpec) -> list[PolicyIssue]:
    issues: list[PolicyIssue] = []

    for service in sorted(topology.services, key=lambda item: item.id):
        issues.extend(_service_issues(service, topology.deployment.environment))

    for datastore in sorted(topology.datastores, key=lambda item: item.id):
        issues.extend(_datastore_issues(datastore))

    for edge in sorted(topology.edges, key=lambda item: item.id):
        issues.extend(_edge_issues(edge))

    return issues


def has_errors(issues: list[PolicyIssue]) -> bool:
    return any(issue.severity == "error" for issue in issues)


def _service_issues(service: ServiceNode, environment: str) -> list[PolicyIssue]:
    issues: list[PolicyIssue] = []

    if not _is_pinned_image(service.image):
        issues.append(
            _issue(
                "error",
                "W2P-SVC-001",
                f"service {service.id} must use a pinned container image tag or digest",
                f"service:{service.id}",
            )
        )

    if service.security.public and not service.security.require_auth:
        issues.append(
            _issue(
                "error",
                "W2P-SVC-002",
                f"public service {service.id} must require authentication",
                f"service:{service.id}",
            )
        )

    if service.security.public and not service.ports:
        issues.append(
            _issue(
                "error",
                "W2P-SVC-009",
                f"public service {service.id} must declare at least one port",
                f"service:{service.id}",
            )
        )

    if service.security.public and not service.security.tls_required:
        issues.append(
            _issue(
                "error",
                "W2P-SVC-003",
                f"public service {service.id} must require TLS",
                f"service:{service.id}",
            )
        )

    if not service.security.run_as_non_root:
        issues.append(
            _issue(
                "error",
                "W2P-SVC-004",
                f"service {service.id} must run as a non-root container user",
                f"service:{service.id}",
            )
        )

    if not service.security.read_only_root_fs:
        issues.append(
            _issue(
                "warning",
                "W2P-SVC-005",
                f"service {service.id} should use a read-only root filesystem",
                f"service:{service.id}",
            )
        )

    if environment == "prod" and service.kind in {"api", "frontend", "gateway"} and service.replicas < 2:
        issues.append(
            _issue(
                "warning",
                "W2P-SVC-006",
                f"production service {service.id} should run at least two replicas",
                f"service:{service.id}",
            )
        )

    if service.security.egress == "internet":
        issues.append(
            _issue(
                "warning",
                "W2P-SVC-007",
                f"service {service.id} declares unrestricted internet egress intent",
                f"service:{service.id}",
            )
        )

    for key, value in sorted(service.env.items()):
        if SECRET_KEY_PATTERN.search(key) and not _is_secret_reference(value):
            issues.append(
                _issue(
                    "error",
                    "W2P-SVC-008",
                    f"secret-like environment variable {key} on {service.id} must use a secret reference",
                    f"service:{service.id}:env:{key}",
                )
            )

    return issues


def _datastore_issues(datastore: DataStore) -> list[PolicyIssue]:
    issues: list[PolicyIssue] = []

    if datastore.public_access:
        issues.append(
            _issue(
                "error",
                "W2P-DS-001",
                f"datastore {datastore.id} must not allow public access",
                f"datastore:{datastore.id}",
            )
        )

    if not datastore.encrypted_at_rest:
        issues.append(
            _issue(
                "error",
                "W2P-DS-002",
                f"datastore {datastore.id} must be encrypted at rest",
                f"datastore:{datastore.id}",
            )
        )

    if datastore.kind in {"postgres", "mysql", "redis"} and not datastore.backups_enabled:
        issues.append(
            _issue(
                "warning",
                "W2P-DS-003",
                f"datastore {datastore.id} should have backups enabled",
                f"datastore:{datastore.id}",
            )
        )

    return issues


def _edge_issues(edge: Edge) -> list[PolicyIssue]:
    issues: list[PolicyIssue] = []

    if edge.protocol in {"http", "tcp"} and not edge.encrypted:
        issues.append(
            _issue(
                "error",
                "W2P-EDGE-001",
                f"edge {edge.id} uses an unencrypted transport",
                f"edge:{edge.id}",
            )
        )

    if edge.protocol in {"https", "grpc", "postgres", "mysql", "redis", "s3", "sqs"} and not edge.auth_required:
        issues.append(
            _issue(
                "error",
                "W2P-EDGE-002",
                f"edge {edge.id} must require authentication or identity-based authorization",
                f"edge:{edge.id}",
            )
        )

    return issues


def _is_secret_reference(value: str) -> bool:
    return value.startswith(("secret://", "ssm://", "arn:aws:secretsmanager:", "arn:aws:ssm:"))


def _is_pinned_image(image: str) -> bool:
    if "@sha256:" in image:
        return True
    image_name = image.rsplit("/", 1)[-1]
    return ":" in image_name and not image_name.endswith(":latest")


def _issue(severity: str, code: str, message: str, target: str) -> PolicyIssue:
    return PolicyIssue(severity=severity, code=code, message=message, target=target)
