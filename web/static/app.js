const fileInput = document.querySelector("#fileInput");
const chooseButton = document.querySelector("#chooseButton");
const dropZone = document.querySelector("#dropZone");
const settingsForm = document.querySelector("#settingsForm");
const accuracyToggle = document.querySelector("#accuracyToggle");
const modelSelect = document.querySelector("#modelSelect");
const jobsList = document.querySelector("#jobsList");
const jobCount = document.querySelector("#jobCount");
const previewText = document.querySelector("#previewText");
const statusLine = document.querySelector("#statusLine");
const refreshButton = document.querySelector("#refreshButton");
const copyButton = document.querySelector("#copyButton");
const openOutputButton = document.querySelector("#openOutputButton");
const recordButton = document.querySelector("#recordButton");
const stopButton = document.querySelector("#stopButton");
const recordTimer = document.querySelector("#recordTimer");
const recordDot = document.querySelector("#recordDot");
const meter = document.querySelector(".meter");
const uploadPanel = document.querySelector("#uploadPanel");
const uploadList = document.querySelector("#uploadList");
const uploadCount = document.querySelector("#uploadCount");

let selectedJobId = null;
let latestJobs = [];
let activeUploads = [];
let mediaRecorder = null;
let recordedChunks = [];
let recordStart = 0;
let recordTimerHandle = null;

chooseButton.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => submitFiles([...fileInput.files]));
refreshButton.addEventListener("click", loadJobs);
copyButton.addEventListener("click", copyPreview);
openOutputButton.addEventListener("click", revealSelectedOutput);
recordButton.addEventListener("click", startRecording);
stopButton.addEventListener("click", stopRecording);

accuracyToggle.addEventListener("change", () => {
  const beamInput = settingsForm.elements.beamSize;
  if (accuracyToggle.checked) {
    modelSelect.value = "large-v3";
    beamInput.value = "8";
  } else {
    modelSelect.value = "small";
    beamInput.value = "5";
  }
});

["dragenter", "dragover"].forEach((eventName) => {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.add("dragging");
  });
});

["dragleave", "drop"].forEach((eventName) => {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.remove("dragging");
  });
});

dropZone.addEventListener("drop", (event) => {
  const files = [...event.dataTransfer.files];
  submitFiles(files);
});

async function submitFiles(files) {
  if (!files.length) return;

  const formData = buildSettingsFormData();
  files.forEach((file) => formData.append("files", file));
  const uploadItems = files.map((file) => ({
    id: crypto.randomUUID(),
    name: file.name,
    size: file.size,
    progress: 0,
    state: "Waiting",
  }));
  activeUploads = [...uploadItems, ...activeUploads];
  renderUploads();

  try {
    statusLine.textContent = `Uploading ${files.length} file${files.length === 1 ? "" : "s"}`;
    const payload = await uploadWithProgress(formData, uploadItems);
    uploadItems.forEach((item) => {
      item.progress = 100;
      item.state = "Queued";
    });
    if (payload.jobs?.[0]) {
      selectedJobId = payload.jobs[0].id;
    }
    renderUploads();
    window.setTimeout(() => {
      activeUploads = activeUploads.filter((item) => !uploadItems.includes(item));
      renderUploads();
    }, 4500);
  } catch (error) {
    uploadItems.forEach((item) => {
      item.state = "Failed";
    });
    statusLine.textContent = error.message || "Upload failed";
    renderUploads();
    return;
  }

  fileInput.value = "";
  await loadJobs();
}

function uploadWithProgress(formData, uploadItems) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/jobs");
    xhr.responseType = "json";

    xhr.upload.addEventListener("loadstart", () => {
      uploadItems.forEach((item) => {
        item.state = "Uploading";
        item.progress = 0;
      });
      renderUploads();
    });

    xhr.upload.addEventListener("progress", (event) => {
      if (!event.lengthComputable) {
        uploadItems.forEach((item) => {
          item.state = "Uploading";
        });
        renderUploads();
        return;
      }

      const percent = Math.max(1, Math.min(99, Math.round((event.loaded / event.total) * 100)));
      uploadItems.forEach((item) => {
        item.state = "Uploading";
        item.progress = percent;
      });
      statusLine.textContent = `Uploading ${percent}%`;
      renderUploads();
    });

    xhr.upload.addEventListener("load", () => {
      uploadItems.forEach((item) => {
        item.state = "Saving locally";
        item.progress = 100;
      });
      statusLine.textContent = "Saving locally";
      renderUploads();
    });

    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(xhr.response || JSON.parse(xhr.responseText));
      } else {
        reject(new Error(xhr.response?.detail || xhr.responseText || `Upload failed (${xhr.status})`));
      }
    });

    xhr.addEventListener("error", () => reject(new Error("Upload failed")));
    xhr.addEventListener("abort", () => reject(new Error("Upload cancelled")));
    xhr.send(formData);
  });
}

function buildSettingsFormData() {
  const formData = new FormData();
  const form = settingsForm.elements;
  formData.append("model", form.model.value);
  formData.append("language", form.language.value.trim());
  formData.append("task", form.translate.checked ? "translate" : "transcribe");
  formData.append("device", form.device.value);
  formData.append("compute_type", form.device.value === "cuda" ? "float16" : "auto");
  formData.append("beam_size", form.beamSize.value);
  formData.append("vad", form.vad.checked ? "true" : "false");
  formData.append("note_gap_seconds", form.noteGapSeconds.value);
  formData.append("max_note_minutes", "8");
  formData.append("min_silence_ms", "1500");
  formData.append("speech_pad_ms", "300");
  return formData;
}

async function loadJobs() {
  const response = await fetch("/api/jobs");
  const payload = await response.json();
  latestJobs = payload.jobs;

  if (!selectedJobId && latestJobs.length) {
    selectedJobId = latestJobs[0].id;
  }

  if (selectedJobId && !latestJobs.some((job) => job.id === selectedJobId) && latestJobs.length) {
    selectedJobId = latestJobs[0].id;
  }

  const newestFailed = latestJobs.find((job) => job.status === "failed");
  if (newestFailed && newestFailed.id !== selectedJobId) {
    selectedJobId = newestFailed.id;
  }

  renderJobs();
  if (selectedJobId) {
    const selected = latestJobs.find((job) => job.id === selectedJobId);
    if (selected) renderPreview(selected);
  }
  if (activeUploads.length) {
    statusLine.textContent = activeUploads[0].state;
    return;
  }
  const running = latestJobs.find((job) => job.status === "running");
  const failed = latestJobs.find((job) => job.status === "failed");
  if (running) {
    statusLine.textContent = `Running: ${(running.progress || []).at(-1) || "Working"}`;
  } else if (failed) {
    statusLine.textContent = `Failed: ${failed.error || "Open the failed job for details"}`;
  } else {
    statusLine.textContent = "Ready";
  }
}

function renderUploads() {
  uploadCount.textContent = activeUploads.length;
  uploadPanel.classList.toggle("hidden", activeUploads.length === 0);
  uploadList.innerHTML = "";

  activeUploads.forEach((item) => {
    const row = document.createElement("div");
    row.className = "upload-row";
    row.innerHTML = `
      <div class="upload-main">
        <div class="upload-name" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</div>
        <div class="upload-state">${escapeHtml(item.state)}</div>
      </div>
      <div class="progress-track"><div class="progress-fill" style="width: ${item.progress}%"></div></div>
      <div class="upload-meta">${formatBytes(item.size)} - ${item.progress}%</div>
    `;
    uploadList.appendChild(row);
  });
}

function renderJobs() {
  jobCount.textContent = latestJobs.length;
  jobsList.innerHTML = "";

  if (!latestJobs.length) {
    const empty = document.createElement("div");
    empty.className = "job-row";
    empty.innerHTML = `<div class="job-meta">No jobs yet.</div>`;
    jobsList.appendChild(empty);
    return;
  }

  latestJobs.forEach((job) => {
    const row = document.createElement("button");
    row.type = "button";
    row.className = `job-row ${job.id === selectedJobId ? "selected" : ""}`;
    row.innerHTML = `
      <div class="job-main">
        <div class="job-name" title="${escapeHtml(job.originalName)}">${escapeHtml(job.originalName)}</div>
        <span class="status-pill status-${job.status}">${job.status}</span>
      </div>
      <div class="job-meta">${escapeHtml(job.settings.model)} - ${escapeHtml(job.settings.task)} - ${escapeHtml(job.settings.device)}</div>
      <div class="job-progress">${escapeHtml((job.progress || []).at(-1) || "Queued")}</div>
      ${job.error ? `<div class="job-error">${escapeHtml(job.error)}</div>` : ""}
    `;
    row.addEventListener("click", () => {
      selectedJobId = job.id;
      renderJobs();
      renderPreview(job);
    });
    jobsList.appendChild(row);
  });
}

function renderPreview(job) {
  copyButton.disabled = job.status !== "finished";
  openOutputButton.disabled = job.status !== "finished";

  if (job.status === "failed") {
    const details = [
      "Transcription failed.",
      "",
      job.error || "No error detail was reported.",
      "",
      job.errorLogPath ? `Error log: ${job.errorLogPath}` : "",
      "",
      "Recent progress:",
      ...(job.progress || []),
    ].filter((line) => line !== null);
    previewText.textContent = details.join("\n");
    return;
  }

  if (job.status !== "finished") {
    previewText.textContent = (job.progress || []).join("\n") || "Queued.";
    return;
  }

  previewText.textContent = job.preview || "Output is ready.";
}

async function copyPreview() {
  await navigator.clipboard.writeText(previewText.textContent);
  statusLine.textContent = "Copied";
}

async function revealSelectedOutput() {
  if (!selectedJobId) return;
  await fetch(`/api/jobs/${selectedJobId}/reveal`, { method: "POST" });
}

async function startRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  recordedChunks = [];
  mediaRecorder = new MediaRecorder(stream, { mimeType: pickMimeType() });

  mediaRecorder.ondataavailable = (event) => {
    if (event.data.size > 0) recordedChunks.push(event.data);
  };
  mediaRecorder.onstop = () => {
    stream.getTracks().forEach((track) => track.stop());
    submitRecording();
  };

  mediaRecorder.start(1000);
  recordStart = Date.now();
  recordButton.disabled = true;
  stopButton.disabled = false;
  recordDot.classList.add("active");
  meter.classList.add("recording");
  recordTimerHandle = setInterval(updateRecordTimer, 500);
  updateRecordTimer();
}

function stopRecording() {
  if (!mediaRecorder || mediaRecorder.state === "inactive") return;
  mediaRecorder.stop();
  recordButton.disabled = false;
  stopButton.disabled = true;
  recordDot.classList.remove("active");
  meter.classList.remove("recording");
  clearInterval(recordTimerHandle);
}

async function submitRecording() {
  const extension = pickMimeType().includes("ogg") ? "ogg" : "webm";
  const blob = new Blob(recordedChunks, { type: pickMimeType() });
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const file = new File([blob], `recording-${stamp}.${extension}`, { type: blob.type });
  await submitFiles([file]);
  recordTimer.textContent = "00:00";
}

function pickMimeType() {
  if (MediaRecorder.isTypeSupported("audio/webm;codecs=opus")) return "audio/webm;codecs=opus";
  if (MediaRecorder.isTypeSupported("audio/ogg;codecs=opus")) return "audio/ogg;codecs=opus";
  return "";
}

function updateRecordTimer() {
  const seconds = Math.floor((Date.now() - recordStart) / 1000);
  const minutes = String(Math.floor(seconds / 60)).padStart(2, "0");
  const rest = String(seconds % 60).padStart(2, "0");
  recordTimer.textContent = `${minutes}:${rest}`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / Math.pow(1024, index);
  return `${value.toFixed(value >= 10 || index === 0 ? 0 : 1)} ${units[index]}`;
}

loadJobs();
setInterval(loadJobs, 2500);
