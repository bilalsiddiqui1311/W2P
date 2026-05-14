from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles

from .ai.chatbot import generate_chat_reply
from .ai.providers import image_to_topology, model_catalog
from .app_models import (
    AIModelDescriptor,
    AssistantQueryRequest,
    AssistantQueryResponse,
    AuthResponse,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    CodebaseDetail,
    CodebaseSummary,
    LoginRequest,
    ProfileUpdateRequest,
    SaveTopologyRequest,
    SignupRequest,
    TerraformValidationRequest,
    TerraformValidationResult,
    UserProfile,
)
from .compiler import compile_topology
from .downloads import safe_archive_name, terraform_file_count, terraform_zip_bytes
from .extractor import extract_topology
from .models import (
    CompileRequest,
    CompileResponse,
    GeneratedFile,
    PolicyIssue,
    TopologySpec,
    VisualDiagram,
    topology_json_schema,
    visual_json_schema,
)
from .storage import (
    authenticate_user,
    clear_chat_messages,
    create_codebase,
    create_chat_message,
    create_session,
    create_user,
    delete_codebase,
    get_codebase,
    get_user_for_token,
    initialize_storage,
    list_chat_messages,
    list_codebases,
    update_user,
)
from .validation import validate_terraform_files

app = FastAPI(
    title="W2P Compiler",
    version="0.1.0",
    summary="Compile normalized architecture diagrams into secure production scaffolds.",
)
security = HTTPBearer(auto_error=False)
initialize_storage()


def _current_user(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> dict:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    user = get_user_for_token(credentials.credentials)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return user


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "w2p"}


@app.get("/v1/topology/schema")
def get_topology_schema() -> dict:
    return topology_json_schema()


@app.get("/v1/diagram/schema")
def get_diagram_schema() -> dict:
    return visual_json_schema()


@app.post("/v1/extract", response_model=TopologySpec)
def extract(diagram: VisualDiagram) -> TopologySpec:
    return extract_topology(diagram)


@app.post("/v1/compile", response_model=CompileResponse)
def compile_endpoint(request: CompileRequest) -> CompileResponse:
    return compile_topology(request.topology)


@app.get("/v1/ai/models", response_model=list[AIModelDescriptor])
def models() -> list[AIModelDescriptor]:
    return model_catalog()


@app.post("/v1/auth/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def signup(request: SignupRequest) -> AuthResponse:
    name = request.name or request.email.split("@", 1)[0]
    try:
        user = create_user(request.email, name, request.password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    token = create_session(user["id"])
    return AuthResponse(token=token, user=UserProfile.model_validate(user))


@app.post("/v1/auth/login", response_model=AuthResponse)
def login(request: LoginRequest) -> AuthResponse:
    user = authenticate_user(request.email, request.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    token = create_session(user["id"])
    return AuthResponse(token=token, user=UserProfile.model_validate(user))


@app.get("/v1/me", response_model=UserProfile)
def profile(user: dict = Depends(_current_user)) -> UserProfile:
    return UserProfile.model_validate(user)


@app.patch("/v1/me", response_model=UserProfile)
def update_profile(request: ProfileUpdateRequest, user: dict = Depends(_current_user)) -> UserProfile:
    try:
        updated = update_user(
            user["id"],
            email=request.email,
            name=request.name,
            password=request.password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return UserProfile.model_validate(updated)


@app.get("/v1/codebases", response_model=list[CodebaseSummary])
def user_codebases(user: dict = Depends(_current_user)) -> list[CodebaseSummary]:
    return [CodebaseSummary.model_validate(item) for item in list_codebases(user["id"])]


@app.post("/v1/codebases", response_model=CodebaseDetail, status_code=status.HTTP_201_CREATED)
def save_topology(request: SaveTopologyRequest, user: dict = Depends(_current_user)) -> CodebaseDetail:
    compile_response = compile_topology(request.topology)
    validation = validate_terraform_files({item.path: item.content for item in compile_response.generated_files})
    row = create_codebase(
        user_id=user["id"],
        name=request.name,
        provider=request.provider,
        model=request.model,
        compile_response=compile_response,
        topology=request.topology,
        validation=validation,
        agent_notes=[],
    )
    return _codebase_detail(row)


@app.get("/v1/codebases/{codebase_id}", response_model=CodebaseDetail)
def codebase_detail(codebase_id: str, user: dict = Depends(_current_user)) -> CodebaseDetail:
    row = get_codebase(user["id"], codebase_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Codebase not found")
    return _codebase_detail(row)


@app.delete("/v1/codebases/{codebase_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_codebase(codebase_id: str, user: dict = Depends(_current_user)) -> None:
    if not delete_codebase(user["id"], codebase_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Codebase not found")


@app.get("/v1/codebases/{codebase_id}/terraform.zip")
def download_terraform(codebase_id: str, user: dict = Depends(_current_user)) -> Response:
    row = get_codebase(user["id"], codebase_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Codebase not found")

    detail = _codebase_detail(row)
    if terraform_file_count(detail.generated_files) == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No Terraform files available")

    filename = safe_archive_name(detail.name)
    return Response(
        content=terraform_zip_bytes(detail.generated_files),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/v1/agent/image-to-terraform", response_model=CodebaseDetail, status_code=status.HTTP_201_CREATED)
async def image_to_terraform_endpoint(
    name: str = Form(..., min_length=2, max_length=120),
    provider: str = Form("local-heuristic", max_length=80),
    model: str | None = Form(None, max_length=120),
    deployment_provider: Literal["aws", "azure", "gcp"] = Form("aws"),
    deployment_region: str = Form("us-east-1", min_length=2, max_length=40),
    deployment_environment: Literal["dev", "staging", "prod"] = Form("dev"),
    image: UploadFile = File(...),
    user: dict = Depends(_current_user),
) -> CodebaseDetail:
    content_type = image.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Upload must be an image")

    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded image is empty")
    if len(image_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Image must be 10MB or smaller")

    result = image_to_topology(
        image_bytes=image_bytes,
        filename=image.filename or "whiteboard.png",
        owner=user["email"],
        name=name,
        provider=provider,
        model=model,
        deployment_provider=deployment_provider,
        deployment_region=deployment_region,
        deployment_environment=deployment_environment,
    )
    compile_response = compile_topology(result.topology)
    validation = validate_terraform_files({item.path: item.content for item in compile_response.generated_files})
    row = create_codebase(
        user_id=user["id"],
        name=name,
        provider=result.provider,
        model=result.model,
        compile_response=compile_response,
        topology=result.topology,
        validation=validation,
        agent_notes=result.notes,
    )
    return _codebase_detail(row)


@app.post("/v1/validate/terraform", response_model=TerraformValidationResult)
def validate_terraform(request: TerraformValidationRequest, user: dict = Depends(_current_user)) -> TerraformValidationResult:
    return validate_terraform_files({item.path: item.content for item in request.files})


@app.post("/v1/assistant/query", response_model=AssistantQueryResponse)
def assistant_query(request: AssistantQueryRequest, user: dict = Depends(_current_user)) -> AssistantQueryResponse:
    codebase = None
    if request.codebase_id:
        codebase = get_codebase(user["id"], request.codebase_id)
        if codebase is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Codebase not found")
    return _assistant_response(request.message, codebase)


@app.get("/v1/chat/messages", response_model=list[ChatMessage])
def chat_history(user: dict = Depends(_current_user)) -> list[ChatMessage]:
    return [ChatMessage.model_validate(item) for item in list_chat_messages(user["id"])]


@app.delete("/v1/chat/messages", status_code=status.HTTP_204_NO_CONTENT)
def clear_chat_history(user: dict = Depends(_current_user)) -> None:
    clear_chat_messages(user["id"])


@app.post("/v1/chat/messages", response_model=ChatResponse, status_code=status.HTTP_201_CREATED)
def send_chat_message(request: ChatRequest, user: dict = Depends(_current_user)) -> ChatResponse:
    codebase = None
    if request.codebase_id:
        codebase = get_codebase(user["id"], request.codebase_id)
        if codebase is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Codebase not found")

    history = list_chat_messages(user["id"], limit=12)
    codebases = list_codebases(user["id"])
    user_row = create_chat_message(
        user_id=user["id"],
        role="user",
        content=request.message,
        codebase_id=request.codebase_id,
    )
    reply = generate_chat_reply(
        message=request.message,
        user=user,
        codebase=codebase,
        codebases=codebases,
        history=history,
    )
    assistant_row = create_chat_message(
        user_id=user["id"],
        role="assistant",
        content=reply.answer,
        codebase_id=request.codebase_id,
    )
    return ChatResponse(
        user_message=ChatMessage.model_validate(user_row),
        assistant_message=ChatMessage.model_validate(assistant_row),
        suggestions=reply.suggestions,
    )


def _codebase_detail(row: dict) -> CodebaseDetail:
    return CodebaseDetail(
        id=row["id"],
        name=row["name"],
        provider=row["provider"],
        model=row["model"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        topology=TopologySpec.model_validate_json(row["topology_json"]),
        topology_hash=row["topology_hash"],
        policy_issues=[PolicyIssue.model_validate(item) for item in json.loads(row["policy_issues_json"])],
        validation=TerraformValidationResult.model_validate_json(row["validation_json"]),
        generated_files=[GeneratedFile.model_validate(item) for item in json.loads(row["generated_files_json"])],
        agent_notes=json.loads(row["agent_notes_json"]),
    )


def _assistant_response(message: str, codebase: dict | None) -> AssistantQueryResponse:
    normalized = message.lower()
    related_name = codebase["name"] if codebase else None

    if codebase is not None:
        files = json.loads(codebase["generated_files_json"])
        validation = TerraformValidationResult.model_validate_json(codebase["validation_json"])
        topology = TopologySpec.model_validate_json(codebase["topology_json"])
        terraform_count = sum(1 for item in files if item["path"].startswith("terraform/"))
        if any(token in normalized for token in ["deploy", "cloud", "provider", "region", "environment", "target"]):
            answer = (
                f"{codebase['name']} targets {topology.deployment.provider.upper()} in "
                f"{topology.deployment.region} for {topology.deployment.environment}."
            )
        elif any(token in normalized for token in ["status", "validation", "check", "error", "issue"]):
            answer = (
                f"{codebase['name']} is currently {codebase['status']}. "
                f"Terraform validation is {validation.status} with {len(validation.findings)} finding(s)."
            )
        elif any(token in normalized for token in ["terraform", "download", "zip", "file"]):
            answer = (
                f"{codebase['name']} has {terraform_count} Terraform file(s). "
                "Use the Terraform ZIP action to download only the terraform/ folder."
            )
        else:
            answer = (
                f"{codebase['name']} includes {len(files)} generated artifact(s): Terraform, backend, container, "
                "policy, and schema files."
            )
        return AssistantQueryResponse(
            answer=answer,
            related_codebase_name=related_name,
            suggestions=["Ask about validation", "Ask about Terraform files", "Ask what was generated"],
        )

    if any(token in normalized for token in ["model", "openai", "claude", "gemini", "ai"]):
        answer = (
            "The model selector is live, but external providers need environment keys. "
            "Without keys, W2P uses the local deterministic image-to-topology fallback."
        )
    elif any(token in normalized for token in ["upload", "image", "convert", "generate"]):
        answer = "Upload an image or grab a camera frame, choose a model, then generate. W2P saves the result as a codebase."
    elif any(token in normalized for token in ["deploy", "cloud", "provider", "region", "environment", "target"]):
        answer = "Choose AWS, Azure, or GCP plus region and environment before generation. W2P stores that target in the topology."
    elif any(token in normalized for token in ["profile", "email", "name", "password"]):
        answer = "Profile updates are available from the profile panel after sign-in."
    else:
        answer = "I can answer about your generated codebase, Terraform files, validation status, and model setup."

    return AssistantQueryResponse(answer=answer, suggestions=["Ask about model setup", "Ask about image upload"])


_frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
if _frontend_dir.exists():
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
