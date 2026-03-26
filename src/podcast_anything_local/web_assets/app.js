const state = {
  config: null,
  currentJobId: null,
  currentJob: null,
  liveAudioJobId: null,
  pendingAudioArtifactUrl: null,
  previewSegmentUrls: [],
  previewNextIndex: 0,
  previewPlaybackWanted: false,
  pollTimer: null,
  sourceMode: "url",
  sourcesView: "new",
  sourcesCollapsed: false,
  studioCollapsed: true,
};

const elements = {
  workspaceGrid: document.getElementById("workspace-grid"),
  sourcesPanel: document.getElementById("sources-panel"),
  studioPanel: document.getElementById("studio-panel"),
  sourcesCollapse: document.getElementById("sources-collapse"),
  sourcesExpand: document.getElementById("sources-expand"),
  studioCollapse: document.getElementById("studio-collapse"),
  studioExpand: document.getElementById("studio-expand"),
  jobForm: document.getElementById("job-form"),
  sourceUrl: document.getElementById("source-url"),
  sourceText: document.getElementById("source-text"),
  sourceFile: document.getElementById("source-file"),
  urlFields: document.getElementById("url-fields"),
  textFields: document.getElementById("text-fields"),
  fileFields: document.getElementById("file-fields"),
  sourcesViewButtons: Array.from(document.querySelectorAll("[data-sources-view]")),
  sourcesViewPanels: {
    new: document.getElementById("sources-view-panel-new"),
    history: document.getElementById("sources-view-panel-history"),
  },
  scriptMode: document.getElementById("script-mode"),
  ttsProvider: document.getElementById("tts-provider"),
  settingsModeSummary: document.getElementById("settings-mode-summary"),
  settingsVoiceSummary: document.getElementById("settings-voice-summary"),
  formMessage: document.getElementById("form-message"),
  submitButton: document.getElementById("submit-button"),
  jobDetails: document.getElementById("job-details"),
  jobTitleShell: document.getElementById("job-title-shell"),
  jobTitleValue: document.getElementById("job-title-value"),
  jobStageSpinner: document.getElementById("job-stage-spinner"),
  jobStage: document.getElementById("job-stage"),
  jobError: document.getElementById("job-error"),
  scriptPreview: document.getElementById("script-preview"),
  scriptDownload: document.getElementById("script-download"),
  audioPlayer: document.getElementById("audio-player"),
  audioDownload: document.getElementById("audio-download"),
  artifactList: document.getElementById("artifact-list"),
  recentJobs: document.getElementById("recent-jobs"),
  refreshJobsButton: document.getElementById("refresh-jobs-button"),
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
  elements.retryButton.addEventListener("click", () => void retryCurrentJob());
  elements.scriptMode.addEventListener("change", syncSelectedSettingsSummary);
  elements.ttsProvider.addEventListener("change", syncSelectedSettingsSummary);
  elements.sourcesCollapse.addEventListener("click", () => setPanelCollapsed("sources", true));
  elements.sourcesExpand.addEventListener("click", () => setPanelCollapsed("sources", false));
  elements.studioCollapse.addEventListener("click", () => setPanelCollapsed("studio", true));
  elements.studioExpand.addEventListener("click", () => setPanelCollapsed("studio", false));
  elements.audioPlayer.addEventListener("ended", handleAudioEnded);
  elements.audioPlayer.addEventListener("play", onAudioPlay);
  elements.audioPlayer.addEventListener("pause", onAudioPause);

  for (const button of elements.modeButtons) {
    button.addEventListener("click", () => setSourceMode(button.dataset.sourceMode || "url"));
  }

  for (const button of elements.sourcesViewButtons) {
    button.addEventListener("click", () => setSourcesView(button.dataset.sourcesView || "new"));
  }

  setSourceMode(state.sourceMode);
  setSourcesView(state.sourcesView);
  applyPanelState();
}

async function initialize() {
  await Promise.all([loadConfig(), refreshJobs()]);
}

async function loadConfig() {
  try {
    const payload = await fetchJson("/config");
    state.config = payload;
    fillSelect(elements.ttsProvider, payload.supported_tts_providers);
    syncSelectedSettingsSummary();
  } catch (error) {}
}

function fillSelect(selectElement, values) {
  for (const value of values || []) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = formatProviderName(value);
    selectElement.append(option);
  }
}

function setSourceMode(mode) {
  state.sourceMode = ["url", "text", "file"].includes(mode) ? mode : "url";
  const isUrl = state.sourceMode === "url";
  const isText = state.sourceMode === "text";
  const isFile = state.sourceMode === "file";
  elements.urlFields.classList.toggle("is-hidden", !isUrl);
  elements.textFields.classList.toggle("is-hidden", !isText);
  elements.fileFields.classList.toggle("is-hidden", !isFile);
  elements.sourceUrl.required = isUrl;
  elements.sourceText.required = isText;
  elements.sourceFile.required = isFile;

  for (const button of elements.modeButtons) {
    button.classList.toggle("is-active", button.dataset.sourceMode === state.sourceMode);
  }
}

function setSourcesView(view) {
  state.sourcesView = ["new", "history"].includes(view) ? view : "new";

  for (const button of elements.sourcesViewButtons) {
    button.classList.toggle("is-active", button.dataset.sourcesView === state.sourcesView);
  }

  for (const [panelView, panel] of Object.entries(elements.sourcesViewPanels)) {
    panel.classList.toggle("is-hidden", panelView !== state.sourcesView);
  }
}

async function onSubmitJob(event) {
  event.preventDefault();
  clearMessage();

  try {
    const formData = buildSubmissionPayload();
    setSubmitting(true);
    const job = await fetchJson("/jobs", { method: "POST", body: formData });
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
  } else if (state.sourceMode === "text") {
    const sourceText = elements.sourceText.value.trim();
    if (!sourceText) {
      throw new Error("Provide source text.");
    }
    formData.append("source_text", sourceText);
  } else {
    const file = elements.sourceFile.files[0];
    if (!file) {
      throw new Error("Choose a file to upload.");
    }
    formData.append("source_file", file);
  }

  appendIfValue(formData, "script_mode", elements.scriptMode.value);
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
  elements.submitButton.textContent = isSubmitting ? "Starting…" : "Create podcast";
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
  state.currentJob = null;
  state.liveAudioJobId = null;
  state.pendingAudioArtifactUrl = null;
  state.previewSegmentUrls = [];
  state.previewNextIndex = 0;
  state.previewPlaybackWanted = false;

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
    state.currentJob = job;
    renderJob(job);

    if (shouldLoadArtifacts(job, { includeArtifacts })) {
      await loadArtifacts(jobId);
    }

    if (job.status === "completed" || job.status === "failed") {
      stopPolling();
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

function shouldLoadArtifacts(job, options = {}) {
  const { includeArtifacts = false } = options;
  if (includeArtifacts || job.status === "completed") {
    return true;
  }

  return ["rewriting", "synthesizing"].includes(job.current_stage || "");
}

function renderJob(job) {
  elements.scriptMode.value = job.script_mode || elements.scriptMode.value;
  elements.ttsProvider.value = job.tts_provider || "";
  if (job.title) {
    elements.jobTitleValue.textContent = job.title;
    elements.jobTitleShell.classList.remove("is-hidden");
  } else {
    elements.jobTitleValue.textContent = "";
    elements.jobTitleShell.classList.add("is-hidden");
  }
  elements.jobStage.textContent = job.current_stage || "queued";
  syncSelectedSettingsSummary();
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

  if (shouldUseLiveAudioStream(job)) {
    attachLiveAudioStream(job);
  }
}

async function loadArtifacts(jobId) {
  const artifacts = await fetchJson(`/jobs/${jobId}/artifacts`);
  renderArtifactList(artifacts);
  await Promise.all([loadScriptArtifact(artifacts), loadAudioArtifact(artifacts)]);
}

function renderArtifactList(artifacts) {
  elements.artifactList.replaceChildren();
  const visibleArtifacts = artifacts.filter((artifact) => !isPreviewAudioArtifact(artifact));

  if (!visibleArtifacts.length) {
    const empty = document.createElement("li");
    empty.className = "hint";
    empty.textContent = "No artifacts available yet.";
    elements.artifactList.append(empty);
    return;
  }

  for (const artifact of visibleArtifacts) {
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
    renderScriptPreview(null);
    elements.scriptDownload.classList.add("is-hidden");
    elements.scriptDownload.removeAttribute("href");
    return;
  }

  const text = await fetchText(script.download_path);
  renderScriptPreview(text || "");
  elements.scriptDownload.href = script.download_path;
  elements.scriptDownload.classList.remove("is-hidden");
}

async function loadAudioArtifact(artifacts) {
  const audio = artifacts.find((artifact) => /^audio\.(wav|mp3|flac|aac|opus)$/i.test(artifact.name));

  if (!audio) {
    if (shouldUseLiveAudioStream(state.currentJob)) {
      attachLiveAudioStream(state.currentJob);
      return;
    }
    if (shouldUsePreviewAudioSegments(state.currentJob)) {
      syncPreviewAudioSegments(artifacts);
      return;
    }
    state.liveAudioJobId = null;
    resetPreviewAudioState();
    elements.audioPlayer.classList.add("is-hidden");
    elements.audioPlayer.removeAttribute("src");
    elements.audioDownload.classList.add("is-hidden");
    elements.audioDownload.removeAttribute("href");
    return;
  }

  const cacheBust = Date.now();
  elements.audioDownload.href = audio.download_path;
  elements.audioDownload.classList.remove("is-hidden");
  const artifactUrl = `${audio.download_path}?v=${cacheBust}`;

  if (shouldDeferAudioArtifactSwap(artifactUrl)) {
    state.pendingAudioArtifactUrl = artifactUrl;
    elements.audioPlayer.classList.remove("is-hidden");
    return;
  }

  applySavedAudioArtifact(artifactUrl);
}

function shouldUseLiveAudioStream(job) {
  return Boolean(
    job &&
      job.job_id &&
      job.status === "running" &&
      job.current_stage === "synthesizing" &&
      (job.tts_provider === "elevenlabs" ||
        (job.tts_provider === "openai" && job.script_mode === "single")),
  );
}

function shouldUsePreviewAudioSegments(job) {
  return Boolean(
    job &&
      job.job_id &&
      job.status === "running" &&
      job.current_stage === "synthesizing" &&
      job.tts_provider === "openai" &&
      job.script_mode === "duo",
  );
}

function attachLiveAudioStream(job) {
  if (!shouldUseLiveAudioStream(job)) {
    return;
  }
  if (state.liveAudioJobId === job.job_id) {
    return;
  }

  state.liveAudioJobId = job.job_id;
  state.pendingAudioArtifactUrl = null;
  resetPreviewAudioState();
  elements.audioPlayer.src = `/jobs/${job.job_id}/audio-stream?v=${Date.now()}`;
  elements.audioPlayer.classList.remove("is-hidden");
  elements.audioDownload.classList.add("is-hidden");
  elements.audioDownload.removeAttribute("href");
}

function shouldDeferAudioArtifactSwap(artifactUrl) {
  return (
    (Boolean(state.liveAudioJobId) || isPreviewAudioSource(elements.audioPlayer.currentSrc)) &&
    !elements.audioPlayer.paused &&
    !elements.audioPlayer.ended &&
    !sameAudioSource(elements.audioPlayer.currentSrc, artifactUrl)
  );
}

function handleAudioEnded() {
  if (advancePreviewAudioSegment()) {
    return;
  }
  promotePendingAudioArtifact();
}

function promotePendingAudioArtifact() {
  if (!state.pendingAudioArtifactUrl) {
    return;
  }
  applySavedAudioArtifact(state.pendingAudioArtifactUrl);
}

function applySavedAudioArtifact(artifactUrl) {
  state.pendingAudioArtifactUrl = null;
  state.liveAudioJobId = null;
  resetPreviewAudioState();
  if (!sameAudioSource(elements.audioPlayer.currentSrc, artifactUrl)) {
    elements.audioPlayer.src = artifactUrl;
  }
  elements.audioPlayer.classList.remove("is-hidden");
}

function isLiveAudioSource(url) {
  return normalizeAudioSource(url).includes("/audio-stream");
}

function isPreviewAudioSource(url) {
  return normalizeAudioSource(url).includes("/preview_audio_");
}

function sameAudioSource(currentUrl, nextUrl) {
  return normalizeAudioSource(currentUrl) === normalizeAudioSource(nextUrl);
}

function normalizeAudioSource(url) {
  if (!url) {
    return "";
  }
  try {
    const parsed = new URL(url, window.location.origin);
    return `${parsed.pathname}${parsed.search.replace(/([?&])v=\d+/, "$1").replace(/[?&]$/, "")}`;
  } catch (error) {
    return url.replace(/([?&])v=\d+/, "$1").replace(/[?&]$/, "");
  }
}

function isPreviewAudioArtifact(artifact) {
  return /^preview_audio_\d+\.(wav|mp3)$/i.test(artifact.name);
}

function syncPreviewAudioSegments(artifacts) {
  const previewUrls = artifacts
    .filter((artifact) => isPreviewAudioArtifact(artifact))
    .map((artifact) => artifact.download_path);

  if (!previewUrls.length) {
    return;
  }

  if (!samePreviewQueue(previewUrls)) {
    state.previewSegmentUrls = previewUrls;
  }

  if (!isPreviewAudioSource(elements.audioPlayer.currentSrc)) {
    playPreviewAudioSegment(0, false);
    return;
  }

  if (
    state.previewPlaybackWanted &&
    state.previewNextIndex < state.previewSegmentUrls.length &&
    (elements.audioPlayer.paused || elements.audioPlayer.ended)
  ) {
    playPreviewAudioSegment(state.previewNextIndex, true);
  }
}

function samePreviewQueue(nextUrls) {
  if (state.previewSegmentUrls.length !== nextUrls.length) {
    return false;
  }
  return state.previewSegmentUrls.every((url, index) => url === nextUrls[index]);
}

function playPreviewAudioSegment(index, autoplay) {
  if (index < 0 || index >= state.previewSegmentUrls.length) {
    return false;
  }

  state.liveAudioJobId = null;
  const previewUrl = `${state.previewSegmentUrls[index]}?v=${Date.now()}`;
  state.previewNextIndex = index + 1;
  if (!sameAudioSource(elements.audioPlayer.currentSrc, previewUrl)) {
    elements.audioPlayer.src = previewUrl;
  }
  elements.audioPlayer.classList.remove("is-hidden");
  elements.audioDownload.classList.add("is-hidden");
  elements.audioDownload.removeAttribute("href");
  if (autoplay) {
    void elements.audioPlayer.play().catch(() => {});
  }
  return true;
}

function advancePreviewAudioSegment() {
  if (!isPreviewAudioSource(elements.audioPlayer.currentSrc)) {
    return false;
  }

  if (state.previewNextIndex < state.previewSegmentUrls.length) {
    state.previewPlaybackWanted = true;
    return playPreviewAudioSegment(state.previewNextIndex, true);
  }

  state.previewPlaybackWanted = true;
  return false;
}

function onAudioPlay() {
  if (isPreviewAudioSource(elements.audioPlayer.currentSrc)) {
    state.previewPlaybackWanted = true;
  }
}

function onAudioPause() {
  if (isPreviewAudioSource(elements.audioPlayer.currentSrc) && !elements.audioPlayer.ended) {
    state.previewPlaybackWanted = false;
  }
}

function resetPreviewAudioState() {
  state.previewSegmentUrls = [];
  state.previewNextIndex = 0;
  state.previewPlaybackWanted = false;
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

function formatProviderName(value) {
  if (value === "openai") {
    return "OpenAI";
  }
  if (value === "elevenlabs") {
    return "ElevenLabs";
  }
  if (value === "wave") {
    return "Wave";
  }
  return value || "-";
}

function getSelectedVoiceProviderName() {
  const selected = elements.ttsProvider.value || state.config?.default_tts_provider || "";
  return formatProviderName(selected);
}

function syncSelectedSettingsSummary() {
  const modeLabel = formatScriptMode(elements.scriptMode.value);
  const voiceLabel = getSelectedVoiceProviderName();

  elements.settingsModeSummary.textContent = modeLabel;
  elements.settingsVoiceSummary.textContent = voiceLabel;
}

function renderScriptPreview(text) {
  elements.scriptPreview.replaceChildren();

  if (text === null) {
    elements.scriptPreview.append(createScriptPlaceholder("No script artifact loaded yet."));
    return;
  }

  if (!text.trim()) {
    elements.scriptPreview.append(createScriptPlaceholder("The script artifact is empty."));
    return;
  }

  const lines = text.split(/\r?\n/);
  let currentSpeaker = null;
  let currentTurnLines = [];
  let currentParagraphLines = [];

  function flushTurn() {
    if (!currentSpeaker || !currentTurnLines.length) {
      currentSpeaker = null;
      currentTurnLines = [];
      return;
    }
    elements.scriptPreview.append(createScriptTurn(currentSpeaker, currentTurnLines.join("\n")));
    currentSpeaker = null;
    currentTurnLines = [];
  }

  function flushParagraph() {
    if (!currentParagraphLines.length) {
      currentParagraphLines = [];
      return;
    }
    elements.scriptPreview.append(createScriptParagraph(currentParagraphLines.join(" ")));
    currentParagraphLines = [];
  }

  for (const rawLine of lines) {
    const trimmed = rawLine.trim();
    const speakerMatch = trimmed.match(/^(HOST_A|HOST_B):\s*(.*)$/);

    if (speakerMatch) {
      flushParagraph();
      flushTurn();
      currentSpeaker = speakerMatch[1];
      currentTurnLines = speakerMatch[2] ? [speakerMatch[2]] : [];
      continue;
    }

    if (!trimmed) {
      flushTurn();
      flushParagraph();
      continue;
    }

    if (currentSpeaker) {
      currentTurnLines.push(trimmed);
    } else {
      currentParagraphLines.push(trimmed);
    }
  }

  flushTurn();
  flushParagraph();

  if (!elements.scriptPreview.childElementCount) {
    elements.scriptPreview.append(createScriptPlaceholder("The script artifact is empty."));
  }
}

function createScriptPlaceholder(text) {
  const placeholder = document.createElement("p");
  placeholder.className = "script-placeholder";
  placeholder.textContent = text;
  return placeholder;
}

function createScriptTurn(speaker, body) {
  const turn = document.createElement("section");
  turn.className = `script-turn ${speaker === "HOST_A" ? "script-turn-a" : "script-turn-b"}`;

  const label = document.createElement("span");
  label.className = "script-speaker";
  label.textContent = speaker === "HOST_A" ? "Host A" : "Host B";

  const paragraph = document.createElement("p");
  paragraph.className = "script-line";
  paragraph.textContent = body.trim();

  turn.append(label, paragraph);
  return turn;
}

function createScriptParagraph(text) {
  const paragraph = document.createElement("p");
  paragraph.className = "script-paragraph";
  paragraph.textContent = text;
  return paragraph;
}

function setPanelCollapsed(panel, collapsed) {
  if (panel === "sources") {
    state.sourcesCollapsed = collapsed;
    writePanelPreference("sources", collapsed);
  } else if (panel === "studio") {
    state.studioCollapsed = collapsed;
    writePanelPreference("studio", collapsed);
  }
  applyPanelState();
}

function applyPanelState() {
  state.sourcesCollapsed = readPanelPreference("sources", state.sourcesCollapsed);
  state.studioCollapsed = readPanelPreference("studio", state.studioCollapsed);

  elements.sourcesPanel.classList.toggle("is-collapsed", state.sourcesCollapsed);
  elements.studioPanel.classList.toggle("is-collapsed", state.studioCollapsed);
  elements.workspaceGrid.classList.toggle("sources-collapsed", state.sourcesCollapsed);
  elements.workspaceGrid.classList.toggle("studio-collapsed", state.studioCollapsed);

  elements.sourcesCollapse.setAttribute("aria-expanded", String(!state.sourcesCollapsed));
  elements.sourcesExpand.setAttribute("aria-expanded", String(!state.sourcesCollapsed));
  elements.studioCollapse.setAttribute("aria-expanded", String(!state.studioCollapsed));
  elements.studioExpand.setAttribute("aria-expanded", String(!state.studioCollapsed));
}

function readPanelPreference(panel, fallback) {
  try {
    const raw = window.localStorage.getItem(`podcast-anything:${panel}:collapsed`);
    if (raw === null) {
      return fallback;
    }
    return raw === "true";
  } catch (error) {
    return fallback;
  }
}

function writePanelPreference(panel, collapsed) {
  try {
    window.localStorage.setItem(`podcast-anything:${panel}:collapsed`, String(collapsed));
  } catch (error) {
    return;
  }
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
