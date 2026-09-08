from __future__ import annotations

import argparse
import os
import queue
import shutil
import subprocess
import threading
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .cli import load_model, render_json, render_markdown, safe_stem
from .cli import TranscriptResult, TranscriptSegment


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = PROJECT_ROOT / "web" / "static"
UPLOAD_DIR = PROJECT_ROOT / "uploads"
OUTPUT_DIR = PROJECT_ROOT / "outputs"
RECORDINGS_DIR = PROJECT_ROOT / "recordings"
VALID_COMPUTE_TYPES = {"auto", "default", "int8", "int8_float16", "int8_float32", "int16", "float16", "float32"}


@dataclass
class JobSettings:
    model: str = "small"
    language: str | None = None
    task: str = "transcribe"
    device: str = "cpu"
    compute_type: str = "auto"
    beam_size: int = 5
    vad: bool = True
    min_silence_ms: int = 1500
    speech_pad_ms: int = 300
    note_gap_seconds: float = 30.0
    max_note_minutes: float = 8.0


@dataclass
class Job:
    id: str
    source_path: Path
    original_name: str
    settings: JobSettings
    status: str = "queued"
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    error: str | None = None
    error_log_path: Path | None = None
    markdown_path: Path | None = None
    json_path: Path | None = None
    preview: str = ""
    progress: list[str] = field(default_factory=list)


jobs: dict[str, Job] = {}
jobs_lock = threading.Lock()
job_queue: queue.Queue[str] = queue.Queue()
model_cache: dict[tuple[str, str, str], Any] = {}
worker_started = False


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_dirs()
    start_worker_once()
    yield


app = FastAPI(title="Whisper Voice Log", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Whisper Voice Log web UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    import uvicorn

    ensure_dirs()
    uvicorn.run("whisper_voice_log.web:app", host=args.host, port=args.port, reload=False)
    return 0


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    index_path = STATIC_DIR / "index.html"
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


@app.post("/api/jobs")
async def create_jobs(
    files: list[UploadFile] = File(...),
    model: str = Form("small"),
    language: str = Form(""),
    task: str = Form("transcribe"),
    device: str = Form("cpu"),
    compute_type: str = Form("auto"),
    beam_size: int = Form(5),
    vad: bool = Form(True),
    min_silence_ms: int = Form(1500),
    speech_pad_ms: int = Form(300),
    note_gap_seconds: float = Form(30.0),
    max_note_minutes: float = Form(8.0),
) -> JSONResponse:
    if not files:
        raise HTTPException(status_code=400, detail="No files were uploaded.")

    settings = normalize_settings(
        JobSettings(
        model=model,
        language=language.strip() or None,
        task=task,
        device=device,
        compute_type=compute_type,
        beam_size=beam_size,
        vad=vad,
        min_silence_ms=min_silence_ms,
        speech_pad_ms=speech_pad_ms,
        note_gap_seconds=note_gap_seconds,
        max_note_minutes=max_note_minutes,
        )
    )

    created: list[dict[str, Any]] = []
    for uploaded in files:
        job_id = uuid.uuid4().hex
        suffix = Path(uploaded.filename or "recording.webm").suffix or ".webm"
        original_name = uploaded.filename or f"recording-{job_id}.webm"
        target_dir = RECORDINGS_DIR if original_name.lower().startswith("recording-") else UPLOAD_DIR
        target_path = target_dir / f"{job_id}-{safe_stem(Path(original_name))}{suffix}"

        with target_path.open("wb") as out:
            shutil.copyfileobj(uploaded.file, out)

        job = Job(
            id=job_id,
            source_path=target_path,
            original_name=original_name,
            settings=settings,
            progress=["Queued"],
        )
        with jobs_lock:
            jobs[job_id] = job
        job_queue.put(job_id)
        created.append(job_to_dict(job))

    return JSONResponse({"jobs": created})


@app.get("/api/jobs")
def list_jobs() -> JSONResponse:
    with jobs_lock:
        ordered = sorted(jobs.values(), key=lambda item: item.created_at, reverse=True)
        return JSONResponse({"jobs": [job_to_dict(job) for job in ordered]})


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> JSONResponse:
    job = require_job(job_id)
    return JSONResponse(job_to_dict(job))


@app.get("/api/jobs/{job_id}/output.md")
def get_markdown(job_id: str) -> PlainTextResponse:
    job = require_finished_job(job_id)
    if not job.markdown_path or not job.markdown_path.exists():
        raise HTTPException(status_code=404, detail="Markdown output was not found.")
    return PlainTextResponse(job.markdown_path.read_text(encoding="utf-8"))


@app.get("/api/jobs/{job_id}/download/{kind}")
def download_output(job_id: str, kind: str) -> FileResponse:
    job = require_finished_job(job_id)
    path = job.markdown_path if kind == "markdown" else job.json_path if kind == "json" else None
    if not path or not path.exists():
        raise HTTPException(status_code=404, detail="Output was not found.")
    return FileResponse(path, filename=path.name)


@app.post("/api/jobs/{job_id}/reveal")
def reveal_output(job_id: str) -> JSONResponse:
    job = require_finished_job(job_id)
    path = job.markdown_path or job.json_path
    if not path or not path.exists():
        raise HTTPException(status_code=404, detail="Output was not found.")

    if os.name == "nt":
        subprocess.Popen(["explorer", f"/select,{path}"])
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])
    return JSONResponse({"ok": True})


def ensure_dirs() -> None:
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)


def normalize_settings(settings: JobSettings) -> JobSettings:
    settings.device = settings.device if settings.device in {"cpu", "cuda", "auto"} else "cpu"
    settings.task = settings.task if settings.task in {"transcribe", "translate"} else "transcribe"
    settings.model = settings.model.strip() or "small"
    settings.compute_type = normalized_compute_type(settings.compute_type, settings.device)
    settings.beam_size = max(1, min(settings.beam_size, 12))
    settings.min_silence_ms = max(100, settings.min_silence_ms)
    settings.speech_pad_ms = max(0, settings.speech_pad_ms)
    settings.note_gap_seconds = max(1.0, settings.note_gap_seconds)
    settings.max_note_minutes = max(1.0, settings.max_note_minutes)
    return settings


def normalized_compute_type(compute_type: str, device: str) -> str:
    value = (compute_type or "").strip().lower().replace("-", "_")
    if value in VALID_COMPUTE_TYPES:
        return value
    if device == "cuda":
        return "float16"
    return "auto"


def start_worker_once() -> None:
    global worker_started
    if worker_started:
        return
    worker_started = True
    thread = threading.Thread(target=worker_loop, name="whisper-worker", daemon=True)
    thread.start()


def worker_loop() -> None:
    while True:
        job_id = job_queue.get()
        try:
            process_job(job_id)
        finally:
            job_queue.task_done()


def process_job(job_id: str) -> None:
    job = require_job(job_id)
    original_compute_type = job.settings.compute_type
    job.settings = normalize_settings(job.settings)
    update_job(job, status="running", started_at=time.time())
    if job.settings.compute_type != original_compute_type:
        append_progress(
            job,
            f"Adjusted compute type from {original_compute_type or 'empty'} to {job.settings.compute_type}",
        )
    append_progress(job, "Loading model")

    try:
        settings = job.settings
        model = get_cached_model(settings.model, settings.device, settings.compute_type)
        append_progress(job, "Model ready")
        append_progress(job, "Scanning audio/video for speech")
        result = transcribe_job(job, model)

        markdown_path, json_path = output_paths(job)
        append_progress(job, "Writing outputs")
        markdown_path.write_text(render_markdown(result, settings), encoding="utf-8")
        json_path.write_text(render_json(result), encoding="utf-8")

        preview = markdown_path.read_text(encoding="utf-8")
        update_job(
            job,
            status="finished",
            finished_at=time.time(),
            markdown_path=markdown_path,
            json_path=json_path,
            preview=preview[:12000],
        )
        append_progress(job, "Finished")
    except Exception as exc:
        error_text = str(exc) or exc.__class__.__name__
        error_log_path = OUTPUT_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{job.id[:8]}-error.txt"
        error_log_path.write_text(traceback.format_exc(), encoding="utf-8")
        update_job(
            job,
            status="failed",
            finished_at=time.time(),
            error=error_text,
            error_log_path=error_log_path,
            preview=f"Transcription failed.\n\n{error_text}\n\nError log:\n{error_log_path}",
        )
        append_progress(job, f"Failed: {error_text}")


def get_cached_model(model_name: str, device: str, compute_type: str):
    key = (model_name, device, compute_type)
    if key not in model_cache:
        model_cache[key] = load_model(model_name, device, compute_type)
    return model_cache[key]


def transcribe_job(job: Job, whisper_model) -> TranscriptResult:
    settings = job.settings
    start_time = time.perf_counter()
    segments_iter, info = whisper_model.transcribe(
        str(job.source_path),
        language=settings.language,
        task=settings.task,
        beam_size=settings.beam_size,
        vad_filter=settings.vad,
        vad_parameters={
            "min_silence_duration_ms": settings.min_silence_ms,
            "speech_pad_ms": settings.speech_pad_ms,
        },
    )

    segments: list[TranscriptSegment] = []
    for segment in segments_iter:
        text = " ".join(segment.text.strip().split())
        if not text:
            continue
        item = TranscriptSegment(start=float(segment.start), end=float(segment.end), text=text)
        segments.append(item)
        append_progress(job, f"{item.start:0.1f}s - {item.text[:110]}")

    elapsed = time.perf_counter() - start_time
    if not segments:
        append_progress(job, "No speech segments detected")
    return TranscriptResult(
        source=job.original_name,
        model=settings.model,
        language=getattr(info, "language", None),
        language_probability=getattr(info, "language_probability", None),
        duration_seconds=getattr(info, "duration", None),
        elapsed_seconds=elapsed,
        segments=segments,
    )


def output_paths(job: Job) -> tuple[Path, Path]:
    stem = safe_stem(Path(job.original_name))
    prefix = f"{time.strftime('%Y%m%d-%H%M%S')}-{job.id[:8]}-{stem}"
    return OUTPUT_DIR / f"{prefix}.voice-log.md", OUTPUT_DIR / f"{prefix}.segments.json"


def job_to_dict(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "originalName": job.original_name,
        "sourcePath": str(job.source_path),
        "status": job.status,
        "createdAt": job.created_at,
        "startedAt": job.started_at,
        "finishedAt": job.finished_at,
        "error": job.error,
        "errorLogPath": str(job.error_log_path) if job.error_log_path else None,
        "markdownPath": str(job.markdown_path) if job.markdown_path else None,
        "jsonPath": str(job.json_path) if job.json_path else None,
        "preview": job.preview,
        "progress": job.progress[-80:],
        "settings": job.settings.__dict__,
    }


def update_job(job: Job, **changes: Any) -> None:
    with jobs_lock:
        for key, value in changes.items():
            setattr(job, key, value)


def append_progress(job: Job, message: str) -> None:
    with jobs_lock:
        job.progress.append(message)


def require_job(job_id: str) -> Job:
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job was not found.")
    return job


def require_finished_job(job_id: str) -> Job:
    job = require_job(job_id)
    if job.status != "finished":
        raise HTTPException(status_code=409, detail="Job has not finished yet.")
    return job


if __name__ == "__main__":
    raise SystemExit(main())
