from __future__ import annotations

import json

from ..models import ServiceNode, TopologySpec


def generate_backend_files(topology: TopologySpec) -> dict[str, str]:
    primary = _primary_service(topology)
    port = _primary_port(primary)
    dependencies = _dependencies_for_service(topology, primary.id)

    main_py = f'''from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

SERVICE_ID = {json.dumps(primary.id)}
SERVICE_NAME = {json.dumps(primary.name)}
TOPOLOGY_NAME = {json.dumps(topology.metadata.name)}
DEPENDENCIES: list[dict[str, Any]] = {json.dumps(dependencies, indent=2, sort_keys=True)}

docs_enabled = os.getenv("ENABLE_DOCS", "false").lower() == "true"

app = FastAPI(
    title=f"{{SERVICE_NAME}} API",
    version=os.getenv("APP_VERSION", "0.1.0"),
    docs_url="/docs" if docs_enabled else None,
    redoc_url=None,
    openapi_url="/openapi.json" if docs_enabled else None,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={{"detail": "internal server error"}})


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {{"status": "ok", "service": SERVICE_ID}}


@app.get("/readyz")
def readyz() -> dict[str, object]:
    return {{"status": "ready", "dependencies": DEPENDENCIES}}


@app.get("/metadata")
def metadata() -> dict[str, object]:
    return {{
        "service": SERVICE_ID,
        "name": SERVICE_NAME,
        "topology": TOPOLOGY_NAME,
        "environment": os.getenv("APP_ENV", "dev"),
    }}
'''

    requirements = """fastapi>=0.111,<1.0
uvicorn[standard]>=0.30,<1.0
"""

    readme = f"""# {primary.name}

Generated FastAPI service scaffold for topology `{topology.metadata.name}`.

Run locally:

```bash
uvicorn app.main:app --host 0.0.0.0 --port {port}
```
"""

    return {
        "backend/README.md": readme,
        "backend/app/__init__.py": "",
        "backend/app/main.py": main_py,
        "backend/requirements.txt": requirements,
    }


def _primary_service(topology: TopologySpec) -> ServiceNode:
    public_services = [service for service in topology.services if service.security.public]
    api_services = [service for service in topology.services if service.kind in {"api", "gateway", "frontend"}]
    return sorted(public_services or api_services or topology.services, key=lambda item: item.id)[0]


def _primary_port(service: ServiceNode) -> int:
    if not service.ports:
        return 8000
    return sorted(service.ports, key=lambda item: item.port)[0].port


def _dependencies_for_service(topology: TopologySpec, service_id: str) -> list[dict[str, str]]:
    dependencies: list[dict[str, str]] = []
    for edge in sorted(topology.edges, key=lambda item: item.id):
        if edge.from_node != service_id:
            continue
        dependencies.append(
            {
                "edge": edge.id,
                "target": edge.to_node,
                "protocol": edge.protocol,
                "purpose": edge.purpose,
            }
        )
    return dependencies

