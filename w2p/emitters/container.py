from __future__ import annotations

import re

from ..models import DataStore, ServiceNode, TopologySpec

SECRET_KEY_PATTERN = re.compile(r"(SECRET|TOKEN|PASSWORD|PRIVATE_KEY|API_KEY|DATABASE_URL)", re.IGNORECASE)


def generate_container_files(topology: TopologySpec) -> dict[str, str]:
    primary = _primary_service(topology)
    port = _primary_port(primary)
    return {
        "container/.dockerignore": _dockerignore(),
        "container/Dockerfile": _dockerfile(port),
        "container/docker-compose.yml": _compose(topology),
    }


def _dockerfile(port: int) -> str:
    return f"""FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \\
    PYTHONUNBUFFERED=1 \\
    PIP_NO_CACHE_DIR=1

RUN addgroup --system app && adduser --system --ingroup app app

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

USER app
EXPOSE {port}

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \\
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:{port}/healthz', timeout=2)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "{port}"]
"""


def _dockerignore() -> str:
    return """.venv
__pycache__
.pytest_cache
*.pyc
"""


def _compose(topology: TopologySpec) -> str:
    lines: list[str] = ["services:"]
    datastore_ids = {datastore.id for datastore in topology.datastores}

    for service in sorted(topology.services, key=lambda item: item.id):
        lines.extend(_compose_service(service, topology, datastore_ids))

    for datastore in sorted(topology.datastores, key=lambda item: item.id):
        lines.extend(_compose_datastore(datastore))

    if any(datastore.kind in {"s3", "queue"} for datastore in topology.datastores):
        lines.extend(_compose_localstack(topology.datastores))

    lines.extend(
        [
            "",
            "networks:",
            "  w2p_internal:",
            "    driver: bridge",
            "    internal: true",
        ]
    )

    volumes = _volumes(topology.datastores)
    if volumes:
        lines.append("")
        lines.append("volumes:")
        for volume in volumes:
            lines.append(f"  {volume}: {{}}")

    return "\n".join(lines) + "\n"


def _compose_service(service: ServiceNode, topology: TopologySpec, datastore_ids: set[str]) -> list[str]:
    port = _primary_port(service)
    deps = sorted(
        {
            edge.to_node
            for edge in topology.edges
            if edge.from_node == service.id and edge.to_node in datastore_ids
        }
    )

    lines = [
        f"  {service.id}:",
        "    build:",
        "      context: ../backend",
        "      dockerfile: ../container/Dockerfile",
        f"    image: {service.image}",
        "    read_only: true",
        "    tmpfs:",
        "      - /tmp",
        "    cap_drop:",
        "      - ALL",
        "    security_opt:",
        "      - no-new-privileges:true",
        "    environment:",
        f'      APP_ENV: "{topology.deployment.environment}"',
        '      ENABLE_DOCS: "false"',
        f'      W2P_SERVICE_ID: "{service.id}"',
    ]

    for key, value in sorted(service.env.items()):
        rendered = f'"${{{key}:?set}}"' if SECRET_KEY_PATTERN.search(key) else _quote(value)
        lines.append(f"      {key}: {rendered}")

    if service.ports:
        lines.append("    expose:")
        lines.append(f'      - "{port}"')
    if service.security.public and service.ports:
        lines.append("    ports:")
        lines.append(f'      - "127.0.0.1:{port}:{port}"')
    if deps:
        lines.append("    depends_on:")
        for dep in deps:
            lines.append(f"      - {dep}")
    lines.append("    networks:")
    lines.append("      - w2p_internal")
    return lines


def _compose_datastore(datastore: DataStore) -> list[str]:
    if datastore.kind == "postgres":
        version = datastore.version or "16"
        return [
            f"  {datastore.id}:",
            f"    image: postgres:{version}-alpine",
            "    environment:",
            f'      POSTGRES_DB: "{datastore.id.replace("-", "_")}"',
            '      POSTGRES_USER: "${POSTGRES_USER:?set}"',
            '      POSTGRES_PASSWORD: "${POSTGRES_PASSWORD:?set}"',
            "    volumes:",
            f"      - {datastore.id}_data:/var/lib/postgresql/data",
            "    networks:",
            "      - w2p_internal",
        ]
    if datastore.kind == "mysql":
        version = datastore.version or "8.4"
        return [
            f"  {datastore.id}:",
            f"    image: mysql:{version}",
            "    environment:",
            f'      MYSQL_DATABASE: "{datastore.id.replace("-", "_")}"',
            '      MYSQL_USER: "${MYSQL_USER:?set}"',
            '      MYSQL_PASSWORD: "${MYSQL_PASSWORD:?set}"',
            '      MYSQL_RANDOM_ROOT_PASSWORD: "true"',
            "    volumes:",
            f"      - {datastore.id}_data:/var/lib/mysql",
            "    networks:",
            "      - w2p_internal",
        ]
    if datastore.kind == "redis":
        version = datastore.version or "7"
        return [
            f"  {datastore.id}:",
            f"    image: redis:{version}-alpine",
            '    command: ["redis-server", "--appendonly", "yes", "--requirepass", "${REDIS_PASSWORD:?set}"]',
            "    volumes:",
            f"      - {datastore.id}_data:/data",
            "    networks:",
            "      - w2p_internal",
        ]
    return []


def _compose_localstack(datastores: list[DataStore]) -> list[str]:
    services = []
    if any(datastore.kind == "s3" for datastore in datastores):
        services.append("s3")
    if any(datastore.kind == "queue" for datastore in datastores):
        services.append("sqs")
    return [
        "  localstack:",
        "    image: localstack/localstack:3.5",
        "    environment:",
        f'      SERVICES: "{",".join(services)}"',
        "      DEBUG: \"0\"",
        "    networks:",
        "      - w2p_internal",
    ]


def _volumes(datastores: list[DataStore]) -> list[str]:
    return [
        f"{datastore.id}_data"
        for datastore in sorted(datastores, key=lambda item: item.id)
        if datastore.kind in {"postgres", "mysql", "redis"}
    ]


def _primary_service(topology: TopologySpec) -> ServiceNode:
    public_services = [service for service in topology.services if service.security.public]
    api_services = [service for service in topology.services if service.kind in {"api", "gateway", "frontend"}]
    return sorted(public_services or api_services or topology.services, key=lambda item: item.id)[0]


def _primary_port(service: ServiceNode) -> int:
    if not service.ports:
        return 8000
    return sorted(service.ports, key=lambda item: item.port)[0].port


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

