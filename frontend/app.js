const state = {
  mode: "login",
  token: localStorage.getItem("w2p_token"),
  user: null,
  codebases: [],
  active: null,
  selectedFile: null,
  stream: null,
  models: [],
  profileEditing: false,
  messages: [],
  chatOpen: false,
  chatSuggestions: [],
};

const $ = (id) => document.getElementById(id);

const icons = {
  trash: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"/></svg>',
  download: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12M7 10l5 5 5-5M5 21h14"/></svg>',
};

const cloudRegions = {
  aws: [
    ["us-east-1", "AWS us-east-1"],
    ["us-west-2", "AWS us-west-2"],
    ["eu-west-1", "AWS eu-west-1"],
    ["ap-south-1", "AWS ap-south-1"],
  ],
  azure: [
    ["eastus", "Azure East US"],
    ["westus2", "Azure West US 2"],
    ["westeurope", "Azure West Europe"],
    ["centralindia", "Azure Central India"],
  ],
  gcp: [
    ["us-central1", "GCP us-central1"],
    ["us-east1", "GCP us-east1"],
    ["europe-west1", "GCP europe-west1"],
    ["asia-south1", "GCP asia-south1"],
  ],
};

const defaultChatPrompts = [
  "What model does W2P follow?",
  "Analyze this software architecture",
  "What is missing for SaaS production?",
];

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
    await loadChatMessages();
  } catch (error) {
    localStorage.removeItem("w2p_token");
    state.token = null;
    state.user = null;
    state.codebases = [];
    state.messages = [];
    state.chatOpen = false;
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
  $("generateNavLink").hidden = !signedIn;
  $("generatePanel").hidden = !signedIn;
  $("appShell").classList.toggle("signed-out", !signedIn);
  $("generateButton").disabled = !signedIn;
  $("rerunValidationButton").disabled = !state.active;
  $("downloadTerraformButton").disabled = !state.active;
  $("chatbotShell").hidden = !signedIn;
  $("chatPanel").hidden = !signedIn || !state.chatOpen;
  $("chatToggleButton").setAttribute("aria-expanded", String(signedIn && state.chatOpen));

  renderModels();
  renderDeploymentRegions();
  renderProfile();
  renderCodebases();
  renderActive();
  renderChat();
}

function renderDeploymentRegions() {
  const provider = $("deploymentProviderSelect").value || "aws";
  const select = $("deploymentRegionSelect");
  const current = select.value;
  const regions = cloudRegions[provider] || cloudRegions.aws;
  select.innerHTML = regions
    .map(([value, label]) => `<option value="${escapeHtml(value)}">${escapeHtml(label)}</option>`)
    .join("");
  select.value = regions.some(([value]) => value === current) ? current : regions[0][0];
  $("deploymentStatus").textContent = `${provider.toUpperCase()} / ${select.value}`;
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
    $("profileForm").hidden = true;
    return;
  }
  $("profileName").textContent = state.user.name;
  $("profileEmail").textContent = state.user.email;
  $("avatar").textContent = state.user.name.slice(0, 1).toUpperCase();
  $("codebaseCount").textContent = `${state.codebases.length} saved`;
  $("profileForm").hidden = !state.profileEditing;
  $("editProfileButton").innerHTML = state.profileEditing
    ? '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>Cancel edit'
    : '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>Edit profile';
}

function toggleProfileEdit() {
  state.profileEditing = !state.profileEditing;
  if (state.profileEditing && state.user) {
    $("profileNameInput").value = state.user.name;
    $("profileEmailInput").value = state.user.email;
    $("profilePasswordInput").value = "";
  }
  renderProfile();
}

async function submitProfile(event) {
  event.preventDefault();
  const body = {
    name: $("profileNameInput").value.trim(),
    email: $("profileEmailInput").value.trim(),
  };
  const password = $("profilePasswordInput").value;
  if (password) {
    body.password = password;
  }

  try {
    state.user = await api("/v1/me", {
      method: "PATCH",
      body: JSON.stringify(body),
    });
    state.profileEditing = false;
    render();
    toast("Profile updated");
  } catch (error) {
    toast(error.message);
  }
}

async function loadChatMessages() {
  if (!state.token) {
    state.messages = [];
    return;
  }
  state.messages = await api("/v1/chat/messages");
}

function renderChat() {
  const thread = $("chatThread");
  if (!state.user || !thread) {
    return;
  }
  $("chatContext").textContent = state.active
    ? `Using ${state.active.name} as context`
    : "General workspace assistant";
  $("chatPrompts").innerHTML = (state.chatSuggestions.length ? state.chatSuggestions : defaultChatPrompts)
    .map((prompt) => `<button type="button" data-chat-prompt="${escapeHtml(prompt)}">${escapeHtml(prompt)}</button>`)
    .join("");

  if (!state.messages.length) {
    thread.innerHTML = `
      <div class="chat-empty">
        <strong>Ready when you are.</strong>
        <span>Ask about generation, Terraform, validation, deployment targets, or a selected codebase.</span>
      </div>
    `;
  } else {
    thread.innerHTML = state.messages
      .map(
        (item) => `
          <article class="chat-message ${escapeHtml(item.role)}${item.pending ? " pending" : ""}">
            <span>${item.role === "user" ? "You" : "W2P"}</span>
            <p>${escapeHtml(item.content)}</p>
          </article>
        `,
      )
      .join("");
  }
  thread.scrollTop = thread.scrollHeight;
}

function toggleChat(open = !state.chatOpen) {
  if (!state.user) {
    return;
  }
  state.chatOpen = open;
  render();
}

async function submitChat(event) {
  event.preventDefault();
  if (!state.user) {
    toast("Login or signup before opening the assistant.");
    return;
  }

  const input = $("chatInput");
  const message = input.value.trim();
  if (!message) {
    return;
  }
  await sendChatMessage(message);
}

async function sendChatMessage(message) {
  $("chatInput").value = "";
  $("chatSendButton").disabled = true;
  state.chatOpen = true;
  const pendingUser = {
    id: `pending-user-${Date.now()}`,
    role: "user",
    content: message,
    codebase_id: state.active?.id || null,
    created_at: new Date().toISOString(),
    pending: true,
  };
  const pendingAssistant = {
    id: `pending-assistant-${Date.now()}`,
    role: "assistant",
    content: "Analyzing workspace context...",
    codebase_id: state.active?.id || null,
    created_at: new Date().toISOString(),
    pending: true,
  };
  state.messages.push(pendingUser, pendingAssistant);
  render();

  try {
    const result = await api("/v1/chat/messages", {
      method: "POST",
      body: JSON.stringify({
        message,
        codebase_id: state.active?.id || null,
      }),
    });
    state.messages = state.messages.filter((item) => item.id !== pendingUser.id && item.id !== pendingAssistant.id);
    state.messages.push(result.user_message, result.assistant_message);
    state.chatSuggestions = result.suggestions || [];
  } catch (error) {
    state.messages = state.messages.filter((item) => item.id !== pendingAssistant.id);
    const userItem = state.messages.find((item) => item.id === pendingUser.id);
    if (userItem) {
      userItem.pending = false;
    }
    state.messages.push({
      id: `local-error-${Date.now()}`,
      role: "assistant",
      content: error.message,
      codebase_id: null,
      created_at: new Date().toISOString(),
    });
  } finally {
    $("chatSendButton").disabled = false;
    render();
  }
}

async function clearChat() {
  try {
    await api("/v1/chat/messages", { method: "DELETE" });
    state.messages = [];
    state.chatSuggestions = [];
    renderChat();
    toast("Chat cleared");
  } catch (error) {
    toast(error.message);
  }
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
  $("deploymentStatus").textContent = active
    ? `${active.topology.deployment.provider.toUpperCase()} / ${active.topology.deployment.region}`
    : `${$("deploymentProviderSelect").value.toUpperCase()} / ${$("deploymentRegionSelect").value}`;

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
    toast("Choose an image or grab a camera frame.");
    return;
  }

  const form = new FormData();
  form.append("name", $("codebaseName").value.trim());
  form.append("provider", $("providerSelect").value);
  form.append("deployment_provider", $("deploymentProviderSelect").value);
  form.append("deployment_region", $("deploymentRegionSelect").value);
  form.append("deployment_environment", $("deploymentEnvironmentSelect").value);
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
    toast("Start the camera before grabbing a frame.");
    return;
  }
  const canvas = $("cameraCanvas");
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  canvas.getContext("2d").drawImage(video, 0, 0);
  canvas.toBlob((blob) => {
    if (!blob) {
      toast("Could not grab camera frame.");
      return;
    }
    state.selectedFile = new File([blob], "camera-frame.png", { type: "image/png" });
    $("fileLabel").textContent = "camera-frame.png";
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
$("editProfileButton").addEventListener("click", toggleProfileEdit);
$("profileForm").addEventListener("submit", submitProfile);
$("generateForm").addEventListener("submit", generate);
$("chatToggleButton").addEventListener("click", () => toggleChat());
$("closeChatButton").addEventListener("click", () => toggleChat(false));
$("clearChatButton").addEventListener("click", clearChat);
$("chatForm").addEventListener("submit", submitChat);
$("chatPrompts").addEventListener("click", (event) => {
  const button = event.target.closest("[data-chat-prompt]");
  if (button) {
    sendChatMessage(button.dataset.chatPrompt);
  }
});
$("chatInput").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    $("chatForm").requestSubmit();
  }
});
$("deploymentProviderSelect").addEventListener("change", () => {
  renderDeploymentRegions();
});
$("deploymentRegionSelect").addEventListener("change", () => {
  $("deploymentStatus").textContent = `${$("deploymentProviderSelect").value.toUpperCase()} / ${$("deploymentRegionSelect").value}`;
});
$("deploymentEnvironmentSelect").addEventListener("change", () => {
  $("deploymentStatus").textContent = `${$("deploymentProviderSelect").value.toUpperCase()} / ${$("deploymentRegionSelect").value}`;
});
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
  state.profileEditing = false;
  state.messages = [];
  state.chatOpen = false;
  state.chatSuggestions = [];
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
