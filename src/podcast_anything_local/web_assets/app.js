const state = {
  config: null,
  currentJobId: null,
  pollTimer: null,
  rewriteStream: null,
  liveRewriteText: "",
  sourceMode: "url",
};

const elements = {
  providerSummary: document.getElementById("provider-summary"),
  jobForm: document.getElementById("job-form"),
  sourceUrl: document.getElementById("source-url"),
  sourceFile: document.getElementById("source-file"),
  urlFields: document.getElementById("url-fields"),
  fileFields: document.getElementById("file-fields"),
  scriptMode: document.getElementById("script-mode"),
  rewriteProvider: document.getElementById("rewrite-provider"),
  ttsProvider: document.getElementById("tts-provider"),
  formMessage: document.getElementById("form-message"),
  submitButton: document.getElementById("submit-button"),
  jobEmpty: document.getElementById("job-empty"),
  jobDetails: document.getElementById("job-details"),
  jobId: document.getElementById("job-id"),
  jobStatusBadge: document.getElementById("job-status-badge"),
  jobTitleValue: document.getElementById("job-title-value"),
  jobStageSpinner: document.getElementById("job-stage-spinner"),
  jobStage: document.getElementById("job-stage"),
  jobSourceKind: document.getElementById("job-source-kind"),
  jobScriptMode: document.getElementById("job-script-mode"),
  jobProviders: document.getElementById("job-providers"),
  jobError: document.getElementById("job-error"),
  scriptPreview: document.getElementById("script-preview"),
  scriptDownload: document.getElementById("script-download"),
  audioPlayer: document.getElementById("audio-player"),
  audioDownload: document.getElementById("audio-download"),
  audioEmpty: document.getElementById("audio-empty"),
  artifactList: document.getElementById("artifact-list"),
  recentJobs: document.getElementById("recent-jobs"),
  refreshJobsButton: document.getElementById("refresh-jobs-button"),
  refreshJobButton: document.getElementById("refresh-job-button"),
  retryButton: document.getElementById("retry-button"),
  modeButtons: Array.from(document.querySelectorAll("[data-source-mode]")),
};

document.addEventListener("DOMContentLoaded", () => {
  bindEvents();
  void initialize();
});

function bindEvents() {
  elements.jobForm.addEventListener("submit", onSubmitJob);
  elements.refreshJobsButton.addEventListener("click", () => void refreshJobs());
  elements.refreshJobButton.addEventListener("click", () => {
    if (state.currentJobId) {
      void loadJob(state.currentJobId, { includeArtifacts: true });
    }
  });
  elements.retryButton.addEventListener("click", () => void retryCurrentJob());

  for (const button of elements.modeButtons) {
    button.addEventListener("click", () => setSourceMode(button.dataset.sourceMode || "url"));
  }

  setSourceMode(state.sourceMode);
}

async function initialize() {
  await Promise.all([loadConfig(), refreshJobs()]);
}

async function loadConfig() {
  try {
    const payload = await fetchJson("/config");
    state.config = payload;
    elements.providerSummary.textContent =
      `${payload.default_rewrite_provider} + ${payload.default_tts_provider}`;
    fillSelect(elements.rewriteProvider, payload.supported_rewrite_providers);
    fillSelect(elements.ttsProvider, payload.supported_tts_providers);
  } catch (error) {
    elements.providerSummary.textContent = "Config unavailable";
  }
}

function fillSelect(selectElement, values) {
  for (const value of values || []) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    selectElement.append(option);
  }
}

function setSourceMode(mode) {
  state.sourceMode = mode === "file" ? "file" : "url";
  const isUrl = state.sourceMode === "url";
  elements.urlFields.classList.toggle("is-hidden", !isUrl);
  elements.fileFields.classList.toggle("is-hidden", isUrl);
  elements.sourceUrl.required = isUrl;
  elements.sourceFile.required = !isUrl;

  for (const button of elements.modeButtons) {
    button.classList.toggle("is-active", button.dataset.sourceMode === state.sourceMode);
  }
}

async function onSubmitJob(event) {
  event.preventDefault();
  clearMessage();

  try {
    const formData = buildSubmissionPayload();
    setSubmitting(true);
    const job = await fetchJson("/jobs", { method: "POST", body: formData });
    setMessage(`Started ${job.job_id}. Polling for completion…`);
    await activateJobWithSeed(job.job_id, job);
    await refreshJobs();
  } catch (error) {
    setMessage(error.message, true);
  } finally {
    setSubmitting(false);
  }
}

function buildSubmissionPayload() {
  const formData = new FormData();

  if (state.sourceMode === "url") {
    const sourceUrl = elements.sourceUrl.value.trim();
    if (!sourceUrl) {
      throw new Error("Provide a source URL.");
    }
    formData.append("source_url", sourceUrl);
  } else {
    const file = elements.sourceFile.files[0];
    if (!file) {
      throw new Error("Choose a file to upload.");
    }
    formData.append("source_file", file);
  }

  appendIfValue(formData, "script_mode", elements.scriptMode.value);
  appendIfValue(formData, "rewrite_provider", elements.rewriteProvider.value);
  appendIfValue(formData, "tts_provider", elements.ttsProvider.value);

  return formData;
}

function appendIfValue(formData, key, value) {
  if (value) {
    formData.append(key, value);
  }
}

function setSubmitting(isSubmitting) {
  elements.submitButton.disabled = isSubmitting;
  elements.submitButton.textContent = isSubmitting ? "Starting…" : "Start job";
}

function setMessage(text, isError = false) {
  elements.formMessage.textContent = text;
  elements.formMessage.style.color = isError ? "var(--error)" : "var(--muted)";
}

function clearMessage() {
  elements.formMessage.textContent = "";
  elements.formMessage.style.color = "";
}

async function activateJob(jobId) {
  return activateJobWithSeed(jobId, null);
}

async function activateJobWithSeed(jobId, seedJob) {
  state.currentJobId = jobId;
  if (seedJob) {
    maybeStartRewriteStream(seedJob);
  }

  const job = await loadJob(jobId, { includeArtifacts: true });
  if (job && job.status !== "completed" && job.status !== "failed") {
    startPolling(jobId);
  }
  return job;
}

function startPolling(jobId) {
  stopPolling();
  state.pollTimer = window.setInterval(() => {
    void loadJob(jobId, { includeArtifacts: false, silent: true });
  }, 1600);
}

function stopPolling() {
  if (state.pollTimer !== null) {
    window.clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
}

async function loadJob(jobId, options = {}) {
  const { includeArtifacts = false, silent = false } = options;

  try {
    const job = await fetchJson(`/jobs/${jobId}`);
    state.currentJobId = jobId;
    maybeStartRewriteStream(job);
    renderJob(job);

    if (job.status !== "completed" && job.status !== "failed") {
      await loadRewritePreview(jobId, { silent: true });
    }

    if (job.status === "completed" || includeArtifacts) {
      await loadArtifacts(jobId);
    }

    if (job.status === "completed" || job.status === "failed") {
      stopPolling();
      stopRewriteStream();
      await refreshJobs();
    }

    return job;
  } catch (error) {
    if (!silent) {
      setMessage(error.message, true);
    }
    return null;
  }
}

function renderJob(job) {
  elements.jobEmpty.classList.add("is-hidden");
  elements.jobDetails.classList.remove("is-hidden");
  elements.jobId.textContent = job.job_id;
  elements.jobTitleValue.textContent = job.title || formatPendingTitle(job.status);
  elements.jobStage.textContent = job.current_stage || "queued";
  elements.jobSourceKind.textContent = job.source_kind;
  elements.jobScriptMode.textContent = formatScriptMode(job.script_mode);
  elements.jobProviders.textContent = `${job.rewrite_provider} + ${job.tts_provider}`;
  renderStatusBadge(job.status);
  elements.jobStageSpinner.classList.toggle(
    "is-hidden",
    !["queued", "running"].includes(job.status || ""),
  );

  if (job.error) {
    elements.jobError.textContent = job.error;
    elements.jobError.classList.remove("is-hidden");
  } else {
    elements.jobError.textContent = "";
    elements.jobError.classList.add("is-hidden");
  }
}

function formatPendingTitle(status) {
  if (["queued", "running"].includes(status || "")) {
    return "Generating title...";
  }
  return "Untitled";
}

function renderStatusBadge(status) {
  const label = status || "queued";
  elements.jobStatusBadge.textContent = label;
  elements.jobStatusBadge.className = "status-badge";
  elements.jobStatusBadge.classList.add(`is-${label}`);
}

async function loadArtifacts(jobId) {
  const artifacts = await fetchJson(`/jobs/${jobId}/artifacts`);
  renderArtifactList(artifacts);
  await Promise.all([loadScriptArtifact(artifacts), loadAudioArtifact(artifacts)]);
}

async function loadRewritePreview(jobId, options = {}) {
  const { silent = false } = options;
  try {
    const payload = await fetchJson(`/jobs/${jobId}/rewrite-preview`);
    if (typeof payload.text === "string" && payload.text.trim()) {
      state.liveRewriteText = payload.text;
      if (!elements.scriptDownload.getAttribute("href")) {
        renderLiveRewriteText();
      }
    }
  } catch (error) {
    if (!silent) {
      setMessage(error.message, true);
    }
  }
}

function renderArtifactList(artifacts) {
  elements.artifactList.replaceChildren();

  if (!artifacts.length) {
    const empty = document.createElement("li");
    empty.className = "hint";
    empty.textContent = "No artifacts available yet.";
    elements.artifactList.append(empty);
    return;
  }

  for (const artifact of artifacts) {
    const item = document.createElement("li");
    item.className = "artifact-item";

    const label = document.createElement("div");
    const name = document.createElement("code");
    name.textContent = artifact.name;
    const size = document.createElement("small");
    size.textContent = `${formatBytes(artifact.size_bytes)} • ${artifact.relative_path}`;
    label.append(name, size);

    const link = document.createElement("a");
    link.className = "inline-link";
    link.href = artifact.download_path;
    link.textContent = "Download";

    item.append(label, link);
    elements.artifactList.append(item);
  }
}

async function loadScriptArtifact(artifacts) {
  const script = artifacts.find((artifact) => artifact.name === "script.txt");

  if (!script) {
    elements.scriptPreview.textContent = state.liveRewriteText || "No script artifact loaded yet.";
    elements.scriptDownload.classList.add("is-hidden");
    elements.scriptDownload.removeAttribute("href");
    return;
  }

  const text = await fetchText(script.download_path);
  elements.scriptPreview.textContent = text || "The script artifact is empty.";
  elements.scriptDownload.href = script.download_path;
  elements.scriptDownload.classList.remove("is-hidden");
}

async function loadAudioArtifact(artifacts) {
  const audio = artifacts.find((artifact) => artifact.name.endsWith(".wav") || artifact.name.endsWith(".mp3"));

  if (!audio) {
    elements.audioPlayer.classList.add("is-hidden");
    elements.audioPlayer.removeAttribute("src");
    elements.audioDownload.classList.add("is-hidden");
    elements.audioDownload.removeAttribute("href");
    elements.audioEmpty.classList.remove("is-hidden");
    return;
  }

  const cacheBust = Date.now();
  elements.audioPlayer.src = `${audio.download_path}?v=${cacheBust}`;
  elements.audioPlayer.classList.remove("is-hidden");
  elements.audioDownload.href = audio.download_path;
  elements.audioDownload.classList.remove("is-hidden");
  elements.audioEmpty.classList.add("is-hidden");
}

async function refreshJobs() {
  try {
    const jobs = await fetchJson("/jobs");
    renderRecentJobs(jobs);
  } catch (error) {
    elements.recentJobs.textContent = error.message;
  }
}

function renderRecentJobs(jobs) {
  elements.recentJobs.replaceChildren();

  if (!jobs.length) {
    elements.recentJobs.textContent = "No jobs yet.";
    return;
  }

  for (const job of jobs) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "job-pick";
    button.addEventListener("click", () => void activateJobWithSeed(job.job_id, job));

    const row = document.createElement("div");
    row.className = "job-row";

    const summary = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = job.title || job.job_id;
    const meta = document.createElement("small");
    meta.textContent = `${job.source_kind} • ${formatScriptMode(job.script_mode)} • ${formatTimestamp(job.created_at)}`;
    summary.append(title, meta);

    const badge = document.createElement("span");
    badge.className = `status-badge is-${job.status || "queued"}`;
    badge.textContent = job.status;

    row.append(summary, badge);
    button.append(row);
    elements.recentJobs.append(button);
  }
}

async function retryCurrentJob() {
  if (!state.currentJobId) {
    setMessage("Choose a job before retrying.", true);
    return;
  }

  try {
    const job = await fetchJson(`/jobs/${state.currentJobId}/retry`, { method: "POST" });
    setMessage(`Retried ${job.job_id}.`);
    await activateJobWithSeed(job.job_id, job);
    await refreshJobs();
  } catch (error) {
    setMessage(error.message, true);
  }
}

function maybeStartRewriteStream(job) {
  if (!job || job.job_id !== state.currentJobId) {
    return;
  }

  const streamableProvider = job.rewrite_provider === "ollama";
  const isStreamingStage = ["queued", "running"].includes(job.status || "");
  if (!streamableProvider || !isStreamingStage) {
    if (job.status === "completed" || job.status === "failed") {
      stopRewriteStream();
    }
    return;
  }

  if (state.rewriteStream) {
    return;
  }

  startRewriteStream(job.job_id);
}

function startRewriteStream(jobId) {
  stopRewriteStream();
  state.liveRewriteText = "";
  elements.scriptPreview.textContent = "Streaming rewrite…";
  elements.scriptDownload.classList.add("is-hidden");
  elements.scriptDownload.removeAttribute("href");

  const stream = new EventSource(`/jobs/${jobId}/rewrite-stream`);
  state.rewriteStream = stream;

  stream.addEventListener("rewrite_snapshot", (event) => {
    const payload = parseStreamEvent(event);
    state.liveRewriteText = payload.text || "";
    renderLiveRewriteText();
  });

  stream.addEventListener("rewrite_chunk", (event) => {
    const payload = parseStreamEvent(event);
    state.liveRewriteText += payload.text || "";
    renderLiveRewriteText();
  });

  stream.addEventListener("rewrite_complete", () => {
    stopRewriteStream();
  });

  stream.addEventListener("job_failed", (event) => {
    const payload = parseStreamEvent(event);
    if (payload.error) {
      setMessage(payload.error, true);
    }
    stopRewriteStream();
  });

  stream.onerror = () => {
    if (state.rewriteStream === stream) {
      stream.close();
      state.rewriteStream = null;
    }
  };
}

function stopRewriteStream() {
  if (state.rewriteStream) {
    state.rewriteStream.close();
    state.rewriteStream = null;
  }
}

function renderLiveRewriteText() {
  const text = state.liveRewriteText.trim();
  if (!text) {
    elements.scriptPreview.textContent = "Waiting for rewrite stream…";
    return;
  }
  elements.scriptPreview.textContent = text;
}

function parseStreamEvent(event) {
  try {
    return JSON.parse(event.data || "{}");
  } catch (error) {
    return {};
  }
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  return response.json();
}

async function fetchText(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  return response.text();
}

async function readError(response) {
  const text = await response.text();
  if (!text) {
    return `Request failed with status ${response.status}`;
  }

  try {
    const payload = JSON.parse(text);
    return payload.detail || JSON.stringify(payload);
  } catch (error) {
    return text;
  }
}

function formatTimestamp(value) {
  if (!value) {
    return "unknown time";
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return parsed.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatScriptMode(value) {
  if (value === "duo") {
    return "Two hosts";
  }
  if (value === "single") {
    return "Single host";
  }
  return value || "-";
}

function formatBytes(bytes) {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
