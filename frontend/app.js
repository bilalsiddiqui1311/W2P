const state = {
  mode: "login",
  token: localStorage.getItem("w2p_token"),
  user: null,
  codebases: [],
  active: null,
  selectedFile: null,
  stream: null,
  models: [],
};

const $ = (id) => document.getElementById(id);

const icons = {
  trash: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"/></svg>',
  download: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12M7 10l5 5 5-5M5 21h14"/></svg>',
};

function authHeaders() {
  return state.token ? { Authorization: `Bearer ${state.token}` } : {};
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...authHeaders(),
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(readableError(payload.detail) || `Request failed with ${response.status}`);
  }
  if (response.status === 204) {
    return null;
  }
  return response.json();
}

function readableError(detail) {
  if (!detail) {
    return "";
  }
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        const location = Array.isArray(item.loc) ? item.loc.filter((part) => part !== "body").join(".") : "";
        return [location, item.msg].filter(Boolean).join(": ");
      })
      .join("; ");
  }
  return String(detail);
}

function toast(message) {
  const el = $("toast");
  el.textContent = message;
  el.classList.add("show");
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => el.classList.remove("show"), 3200);
}

function setAuthMode(mode) {
  state.mode = mode;
  $("loginTab").classList.toggle("active", mode === "login");
  $("signupTab").classList.toggle("active", mode === "signup");
  $("nameField").hidden = mode !== "signup";
  $("authSubmitLabel").textContent = mode === "login" ? "Login" : "Create account";
}

async function submitAuth(event) {
  event.preventDefault();
  const body = {
    email: $("emailInput").value.trim(),
    password: $("passwordInput").value,
  };
  if (state.mode === "signup") {
    body.name = $("nameInput").value.trim() || body.email.split("@")[0];
  }
  try {
    const result = await api(`/v1/auth/${state.mode === "login" ? "login" : "signup"}`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    state.token = result.token;
    state.user = result.user;
    localStorage.setItem("w2p_token", state.token);
    await hydrate();
    toast("Signed in");
  } catch (error) {
    toast(error.message);
  }
}

async function hydrate() {
  await loadModels();
  if (!state.token) {
    render();
    return;
  }
  try {
    state.user = await api("/v1/me");
    state.codebases = await api("/v1/codebases");
  } catch (error) {
    localStorage.removeItem("w2p_token");
    state.token = null;
    state.user = null;
    state.codebases = [];
    toast(error.message);
  }
  render();
}

async function loadModels() {
  try {
    state.models = await api("/v1/ai/models");
  } catch {
    state.models = [
      {
        id: "local-heuristic",
        display_name: "Local deterministic diagram heuristic",
        configured: true,
      },
    ];
  }
}

function render() {
  const signedIn = Boolean(state.user);
  $("authPanel").hidden = signedIn;
  $("profilePanel").hidden = !signedIn;
  $("logoutButton").hidden = !signedIn;
  $("generateButton").disabled = !signedIn;
  $("rerunValidationButton").disabled = !state.active;
  $("downloadTerraformButton").disabled = !state.active;

  renderModels();
  renderProfile();
  renderCodebases();
  renderActive();
}

function renderModels() {
  $("providerSelect").innerHTML = state.models
    .map((model) => {
      const suffix = model.configured ? "" : " (fallback)";
      return `<option value="${escapeHtml(model.id)}">${escapeHtml(model.display_name + suffix)}</option>`;
    })
    .join("");
}

function renderProfile() {
  if (!state.user) {
    $("avatar").textContent = "W";
    return;
  }
  $("profileName").textContent = state.user.name;
  $("profileEmail").textContent = state.user.email;
  $("avatar").textContent = state.user.name.slice(0, 1).toUpperCase();
  $("codebaseCount").textContent = `${state.codebases.length} saved`;
}

function renderCodebases() {
  const list = $("codebaseList");
  if (!state.user) {
    list.innerHTML = "";
    return;
  }
  if (!state.codebases.length) {
    list.innerHTML = '<p class="muted">No codebases yet.</p>';
    return;
  }
  list.innerHTML = state.codebases
    .map(
      (item) => `
        <button class="codebase-item" type="button" data-codebase="${escapeHtml(item.id)}">
          <strong>${escapeHtml(item.name)}</strong>
          <span>${escapeHtml(item.status)} | ${escapeHtml(item.provider)} | ${new Date(item.updated_at).toLocaleString()}</span>
        </button>
      `,
    )
    .join("");
}

function renderActive() {
  const active = state.active;
  $("activeTitle").textContent = active ? active.name : "No codebase selected";
  $("topologyStatus").textContent = active ? "Extracted" : "Waiting";
  $("policyStatus").textContent = active ? active.status : "Waiting";
  $("terraformStatus").textContent = active ? active.validation.status : "Waiting";

  const notes = active?.agent_notes || [];
  $("agentNotes").innerHTML = notes
    .map((note) => `<div class="note ${escapeHtml(note.level)}">${escapeHtml(note.message)}</div>`)
    .join("");

  renderFileSelector(active);
  renderValidation(active);
}

function renderFileSelector(active) {
  const select = $("fileSelect");
  if (!active) {
    select.innerHTML = "";
    $("codeOutput").textContent = "Select or generate a codebase to inspect Terraform, backend, container, policy, and schema artifacts.";
    return;
  }
  const terraformFirst = [...active.generated_files].sort((a, b) => {
    const score = (file) => (file.path.startsWith("terraform/") ? 0 : 1);
    return score(a) - score(b) || a.path.localeCompare(b.path);
  });
  select.innerHTML = terraformFirst
    .map((file) => `<option value="${escapeHtml(file.path)}">${escapeHtml(file.path)}</option>`)
    .join("");
  const selected = terraformFirst.find((file) => file.path === select.value) || terraformFirst[0];
  select.value = selected.path;
  $("codeOutput").textContent = selected.content;
}

function renderValidation(active) {
  if (!active) {
    $("validationOutput").innerHTML = '<div class="finding info">Terraform validation will appear after generation.</div>';
    return;
  }
  const findings = active.validation.findings.map(
    (item) => `<div class="finding ${escapeHtml(item.severity)}"><strong>${escapeHtml(item.code)}</strong> ${escapeHtml(item.message)}</div>`,
  );
  const checks = active.validation.tool_checks.map(
    (item) => `<div class="finding ${item.status === "passed" ? "passed" : item.status === "failed" ? "error" : "info"}"><strong>${escapeHtml(item.tool)}</strong> ${escapeHtml(item.summary)}</div>`,
  );
  $("validationOutput").innerHTML = [...findings, ...checks].join("") || '<div class="finding passed">No validation findings.</div>';
}

async function loadCodebase(id) {
  try {
    state.active = await api(`/v1/codebases/${id}`);
    render();
  } catch (error) {
    toast(error.message);
  }
}

async function deleteActive() {
  if (!state.active) {
    return;
  }
  const id = state.active.id;
  try {
    await api(`/v1/codebases/${id}`, { method: "DELETE" });
    state.active = null;
    state.codebases = await api("/v1/codebases");
    render();
    toast("Codebase deleted");
  } catch (error) {
    toast(error.message);
  }
}

async function generate(event) {
  event.preventDefault();
  if (!state.user) {
    toast("Login or signup before generating.");
    return;
  }
  if (!state.selectedFile) {
    toast("Choose an image or capture a camera frame.");
    return;
  }

  const form = new FormData();
  form.append("name", $("codebaseName").value.trim());
  form.append("provider", $("providerSelect").value);
  if ($("modelInput").value.trim()) {
    form.append("model", $("modelInput").value.trim());
  }
  form.append("image", state.selectedFile);

  $("generateButton").disabled = true;
  $("generateButton").textContent = "Generating...";
  try {
    state.active = await api("/v1/agent/image-to-terraform", {
      method: "POST",
      body: form,
    });
    state.codebases = await api("/v1/codebases");
    render();
    toast("Terraform generated and validated");
  } catch (error) {
    toast(error.message);
  } finally {
    $("generateButton").disabled = false;
    $("generateButton").innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M13 2 4 14h7l-1 8 9-12h-7z"/></svg>Generate Terraform';
  }
}

async function startCamera() {
  try {
    state.stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
    $("cameraVideo").srcObject = state.stream;
  } catch (error) {
    toast(error.message || "Camera is unavailable.");
  }
}

function captureFrame() {
  const video = $("cameraVideo");
  if (!state.stream || !video.videoWidth) {
    toast("Start the camera before capturing.");
    return;
  }
  const canvas = $("cameraCanvas");
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  canvas.getContext("2d").drawImage(video, 0, 0);
  canvas.toBlob((blob) => {
    if (!blob) {
      toast("Could not capture camera frame.");
      return;
    }
    state.selectedFile = new File([blob], "camera-capture.png", { type: "image/png" });
    $("fileLabel").textContent = "camera-capture.png";
  }, "image/png");
}

async function rerunValidation() {
  if (!state.active) {
    return;
  }
  try {
    const result = await api("/v1/validate/terraform", {
      method: "POST",
      body: JSON.stringify({ files: state.active.generated_files }),
    });
    state.active.validation = result;
    render();
    toast("Validation complete");
  } catch (error) {
    toast(error.message);
  }
}

async function downloadTerraform() {
  if (!state.active) {
    toast("Generate or select a codebase first.");
    return;
  }
  try {
    const response = await fetch(`/v1/codebases/${state.active.id}/terraform.zip`, {
      headers: authHeaders(),
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(readableError(payload.detail) || `Download failed with ${response.status}`);
    }
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="([^"]+)"/);
    const filename = match ? match[1] : `${state.active.name || "w2p"}-terraform.zip`;
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    toast("Terraform folder downloaded as ZIP");
  } catch (error) {
    toast(error.message);
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

$("loginTab").addEventListener("click", () => setAuthMode("login"));
$("signupTab").addEventListener("click", () => setAuthMode("signup"));
$("authForm").addEventListener("submit", submitAuth);
$("generateForm").addEventListener("submit", generate);
$("startCameraButton").addEventListener("click", startCamera);
$("captureButton").addEventListener("click", captureFrame);
$("rerunValidationButton").addEventListener("click", rerunValidation);
$("downloadTerraformButton").addEventListener("click", downloadTerraform);
$("refreshButton").addEventListener("click", hydrate);
$("logoutButton").addEventListener("click", () => {
  localStorage.removeItem("w2p_token");
  state.token = null;
  state.user = null;
  state.active = null;
  state.codebases = [];
  render();
});

$("fileSelect").addEventListener("change", (event) => {
  const selected = state.active?.generated_files.find((file) => file.path === event.target.value);
  if (selected) {
    $("codeOutput").textContent = selected.content;
  }
});

$("imageInput").addEventListener("change", (event) => {
  const file = event.target.files[0];
  if (file) {
    state.selectedFile = file;
    $("fileLabel").textContent = file.name;
    if (!$("codebaseName").value.trim()) {
      $("codebaseName").value = file.name.replace(/\.[^.]+$/, "").replace(/[^a-zA-Z0-9]+/g, "-").toLowerCase();
    }
  }
});

$("dropzone").addEventListener("dragover", (event) => {
  event.preventDefault();
});

$("dropzone").addEventListener("drop", (event) => {
  event.preventDefault();
  const file = event.dataTransfer.files[0];
  if (file) {
    state.selectedFile = file;
    $("fileLabel").textContent = file.name;
  }
});

$("codebaseList").addEventListener("click", (event) => {
  const item = event.target.closest("[data-codebase]");
  if (item) {
    loadCodebase(item.dataset.codebase);
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Delete" && state.active && event.target === document.body) {
    deleteActive();
  }
});

const deleteButton = document.createElement("button");
deleteButton.className = "ghost-button";
deleteButton.type = "button";
deleteButton.innerHTML = `${icons.trash} Delete active`;
deleteButton.addEventListener("click", deleteActive);
document.querySelector(".validation-panel .section-row").appendChild(deleteButton);

setAuthMode("login");
hydrate();
