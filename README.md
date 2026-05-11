# W2P: Whiteboard-to-Production

W2P compiles normalized architecture diagrams into production-oriented scaffolds:

- Terraform infrastructure-as-code for AWS ECS, encrypted datastores, private networking, and least-privilege defaults.
- FastAPI backend logic with health, metadata, and secure response-header middleware.
- Container scaffolding with pinned base images, non-root runtime, read-only filesystems, and Compose support.
- Policy-as-code checks that run before code generation and are mirrored in Rego under `policies/`.

The compiler is deterministic by design. Visual inputs normalize into `w2p.visual.v1`, then extract into the strict `w2p.topology.v1` JSON contract before any files are emitted.

## Quick Start

Docker Compose is the recommended way to run W2P locally. You do not need a local Python or Node setup for the workbench.

```bash
docker compose up --build
```

The W2P workbench UI will be available at `http://127.0.0.1:8080/`.
OpenAPI will be available at `http://127.0.0.1:8080/docs`.

Stop the stack:

```bash
docker compose down
```

If you want to run the Python app directly for development:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
uvicorn w2p.api:app --reload --port 8080
```

## New Machine Setup

For a fresh machine, you only need:

- Git, to clone the repo.
- Docker with Docker Compose support.
- Internet access for the first image build.

Then run:

```bash
git clone git@github.com:bilalsiddiqui1311/W2P.git
cd W2P
docker compose up --build
```

User accounts and generated codebases are stored in the named Docker volume `w2p_w2p_data`. To reset local app data, run:

```bash
docker compose down -v
```

Compile the sample topology:

```bash
w2p compile examples/topology.json --out generated
```

Generate the topology JSON Schema:

```bash
w2p schema --out schemas/topology.schema.json
```

## API Surface

- `GET /healthz`
- `GET /v1/topology/schema`
- `GET /v1/diagram/schema`
- `GET /v1/ai/models`
- `POST /v1/auth/signup`
- `POST /v1/auth/login`
- `GET /v1/me`
- `GET /v1/codebases`
- `POST /v1/codebases`
- `GET /v1/codebases/{id}`
- `DELETE /v1/codebases/{id}`
- `POST /v1/extract`
- `POST /v1/compile`
- `POST /v1/agent/image-to-terraform`
- `POST /v1/validate/terraform`

`POST /v1/compile` always returns the three required output groups: `terraform/`, `backend/`, and `container/`. It also includes `policy/` and `schema/` artifacts so downstream pipelines can enforce the same contract and guardrails that produced the code.

## Security Defaults

W2P starts from a conservative baseline:

- no public cloud IP assignment for ECS services;
- no ingress CIDRs unless explicitly supplied;
- no egress CIDRs unless explicitly supplied;
- encrypted logs and datastores;
- private subnets required by Terraform variables;
- container images must be pinned and must not use `latest`;
- public services must require authentication and TLS;
- secret-like environment variables must be references, not literal values.

## AI Providers

The first implementation includes a provider catalog for OpenAI vision, Anthropic Claude vision, Google Gemini vision, and a local deterministic fallback. External providers are activated through environment variables:

- `OPENAI_API_KEY` and `W2P_OPENAI_MODEL`
- `ANTHROPIC_API_KEY` and `W2P_ANTHROPIC_MODEL`
- `GOOGLE_API_KEY` and `W2P_GEMINI_MODEL`

Until live provider execution is enabled in a deployment, W2P records the selected provider intent and uses the deterministic local extractor to keep outputs reproducible.

## Terraform Verification

Every generated codebase runs through fast architecture checks and Terraform tooling when available. `terraform fmt -check` runs automatically if the Terraform CLI is installed. Provider-backed `terraform init` and `terraform validate` are opt-in because they may require network access:

```bash
W2P_TERRAFORM_INIT=true uvicorn w2p.api:app --reload --port 8080
```

Validation results are stored with the user's codebase profile record.
