from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path
from typing import Iterable, Sequence


MEDIA_EXTENSIONS = {
    ".aac",
    ".aiff",
    ".alac",
    ".avi",
    ".flac",
    ".m4a",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".ogg",
    ".opus",
    ".wav",
    ".webm",
    ".wma",
}


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class TranscriptResult:
    source: str
    model: str
    language: str | None
    language_probability: float | None
    duration_seconds: float | None
    elapsed_seconds: float
    segments: list[TranscriptSegment]


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return run(args)
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="whisper-voice-log",
        description="Transcribe local audio/video files into timestamped voice-note logs.",
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        type=Path,
        help="Audio/video file(s) or folder(s) to transcribe.",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("outputs"),
        help="Folder for Markdown and JSON transcript files. Default: outputs",
    )
    parser.add_argument(
        "-m",
        "--model",
        default="small",
        help="Whisper model size or local model path. Examples: tiny, base, small, medium, large-v3. Default: small",
    )
    parser.add_argument(
        "--language",
        default=None,
        help="Optional source language code, such as en or sv. Omit for auto-detect.",
    )
    parser.add_argument(
        "--task",
        choices=("transcribe", "translate"),
        default="transcribe",
        help="Transcribe in source language or translate to English. Default: transcribe",
    )
    parser.add_argument(
        "--device",
        default="cpu",
        choices=("auto", "cpu", "cuda"),
        help="Run on CPU or NVIDIA CUDA GPU. Default: cpu",
    )
    parser.add_argument(
        "--compute-type",
        default="auto",
        help="faster-whisper compute type. Useful values: auto, int8, float16. Default: auto",
    )
    parser.add_argument(
        "--beam-size",
        type=int,
        default=5,
        help="Beam size. Higher can improve quality but is slower. Default: 5",
    )
    parser.add_argument(
        "--no-vad",
        action="store_true",
        help="Disable voice activity detection. VAD is enabled by default to skip long dead air.",
    )
    parser.add_argument(
        "--min-silence-ms",
        type=int,
        default=1500,
        help="VAD silence length before splitting speech. Default: 1500",
    )
    parser.add_argument(
        "--speech-pad-ms",
        type=int,
        default=300,
        help="VAD padding around speech chunks. Default: 300",
    )
    parser.add_argument(
        "--note-gap-seconds",
        type=float,
        default=30.0,
        help="Start a new note when the gap between speech segments exceeds this. Default: 30",
    )
    parser.add_argument(
        "--max-note-minutes",
        type=float,
        default=8.0,
        help="Start a new note after this much spoken timeline has accumulated. Default: 8",
    )
    parser.add_argument(
        "--recursive",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Scan input folders recursively. Default: true",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing transcript outputs.",
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="Print common model names and exit.",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    if args.list_models:
        print("tiny, base, small, medium, large-v3")
        print("Tip: start with small for speed, medium/large-v3 for better quality.")
        return 0

    if not args.inputs:
        raise ValueError("Provide at least one audio/video file or folder.")

    ensure_ffmpeg_hint()

    inputs = list(discover_inputs(args.inputs, recursive=args.recursive))
    if not inputs:
        raise ValueError("No supported audio/video files found.")

    args.output_dir.mkdir(parents=True, exist_ok=True)

    whisper_model = load_model(args.model, args.device, args.compute_type)
    failures = 0

    for index, input_path in enumerate(inputs, start=1):
        print(f"[{index}/{len(inputs)}] {input_path}")
        try:
            transcribe_one(input_path, args.output_dir, args, whisper_model)
        except Exception as exc:
            failures += 1
            print(f"  Failed: {exc}", file=sys.stderr)

    if failures:
        print(f"Done with {failures} failed file(s).", file=sys.stderr)
        return 1

    print("Done.")
    return 0


def discover_inputs(paths: Sequence[Path], recursive: bool) -> Iterable[Path]:
    for raw_path in paths:
        path = raw_path.expanduser().resolve()
        if path.is_file():
            if path.suffix.lower() in MEDIA_EXTENSIONS:
                yield path
            continue

        if path.is_dir():
            iterator = path.rglob("*") if recursive else path.glob("*")
            for candidate in iterator:
                if candidate.is_file() and candidate.suffix.lower() in MEDIA_EXTENSIONS:
                    yield candidate.resolve()
            continue

        print(f"Skipping missing path: {raw_path}", file=sys.stderr)


def ensure_ffmpeg_hint() -> None:
    if shutil.which("ffmpeg"):
        return

    print(
        "Warning: ffmpeg was not found on PATH. Most formats still work through PyAV, "
        "but installing ffmpeg is recommended for video/audio compatibility.",
        file=sys.stderr,
    )


def load_model(model_name: str, device: str, compute_type: str):
    if device in {"cuda", "auto"}:
        from .cuda_paths import add_cuda_dll_directories

        add_cuda_dll_directories()

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is not installed. Run setup.ps1, then try again."
        ) from exc

    print(f"Loading model: {model_name} ({device}, {compute_type})")
    return WhisperModel(model_name, device=device, compute_type=compute_type)


def transcribe_one(input_path: Path, output_dir: Path, args: argparse.Namespace, whisper_model) -> None:
    stem = safe_stem(input_path)
    markdown_path = output_dir / f"{stem}.voice-log.md"
    json_path = output_dir / f"{stem}.segments.json"

    if not args.force and markdown_path.exists() and json_path.exists():
        print("  Skipping existing outputs. Use --force to regenerate.")
        return

    vad_parameters = {
        "min_silence_duration_ms": args.min_silence_ms,
        "speech_pad_ms": args.speech_pad_ms,
    }
    start_time = time.perf_counter()

    segments_iter, info = whisper_model.transcribe(
        str(input_path),
        language=args.language,
        task=args.task,
        beam_size=args.beam_size,
        vad_filter=not args.no_vad,
        vad_parameters=vad_parameters,
    )

    segments: list[TranscriptSegment] = []
    for segment in segments_iter:
        text = " ".join(segment.text.strip().split())
        if not text:
            continue
        item = TranscriptSegment(start=float(segment.start), end=float(segment.end), text=text)
        segments.append(item)
        print(f"  {format_timestamp(item.start)} -> {format_timestamp(item.end)}  {item.text[:90]}")

    elapsed = time.perf_counter() - start_time
    result = TranscriptResult(
        source=str(input_path),
        model=args.model,
        language=getattr(info, "language", None),
        language_probability=getattr(info, "language_probability", None),
        duration_seconds=getattr(info, "duration", None),
        elapsed_seconds=elapsed,
        segments=segments,
    )

    markdown_path.write_text(render_markdown(result, args), encoding="utf-8")
    json_path.write_text(render_json(result), encoding="utf-8")
    print(f"  Wrote {markdown_path}")
    print(f"  Wrote {json_path}")


def render_markdown(result: TranscriptResult, args: argparse.Namespace) -> str:
    notes = group_segments(
        result.segments,
        note_gap_seconds=args.note_gap_seconds,
        max_note_seconds=args.max_note_minutes * 60.0,
    )

    lines: list[str] = []
    lines.append(f"# Voice Log: {Path(result.source).name}")
    lines.append("")
    lines.append("## Metadata")
    lines.append("")
    lines.append(f"- Source: `{result.source}`")
    lines.append(f"- Model: `{result.model}`")
    lines.append(f"- Language: `{result.language or 'auto'}`")
    if result.language_probability is not None:
        lines.append(f"- Language probability: `{result.language_probability:.2f}`")
    if result.duration_seconds is not None:
        lines.append(f"- Media duration: `{format_duration(result.duration_seconds)}`")
    lines.append(f"- Transcription time: `{format_duration(result.elapsed_seconds)}`")
    vad_is_enabled = not getattr(args, "no_vad", False)
    if hasattr(args, "vad"):
        vad_is_enabled = bool(getattr(args, "vad"))
    lines.append(f"- VAD dead-air skip: `{'on' if vad_is_enabled else 'off'}`")
    lines.append("")
    lines.append("## Voice Notes")
    lines.append("")

    if not notes:
        lines.append("_No speech segments were detected._")
        lines.append("")
    else:
        for note_number, note in enumerate(notes, start=1):
            start = format_timestamp(note[0].start)
            end = format_timestamp(note[-1].end)
            text = " ".join(segment.text for segment in note)
            lines.append(f"### Note {note_number} ({start} - {end})")
            lines.append("")
            lines.append(text)
            lines.append("")

    lines.append("## Timestamped Transcript")
    lines.append("")
    for segment in result.segments:
        lines.append(
            f"- `{format_timestamp(segment.start)} - {format_timestamp(segment.end)}` {segment.text}"
        )
    lines.append("")
    return "\n".join(lines)


def render_json(result: TranscriptResult) -> str:
    data = asdict(result)
    data["segments"] = [asdict(segment) for segment in result.segments]
    return json.dumps(data, ensure_ascii=False, indent=2)


def group_segments(
    segments: Sequence[TranscriptSegment],
    note_gap_seconds: float,
    max_note_seconds: float,
) -> list[list[TranscriptSegment]]:
    groups: list[list[TranscriptSegment]] = []
    current: list[TranscriptSegment] = []

    for segment in segments:
        if not current:
            current.append(segment)
            continue

        previous = current[-1]
        gap = segment.start - previous.end
        note_span = segment.end - current[0].start
        if gap > note_gap_seconds or note_span > max_note_seconds:
            groups.append(current)
            current = [segment]
        else:
            current.append(segment)

    if current:
        groups.append(current)

    return groups


def safe_stem(path: Path) -> str:
    stem = path.stem.strip() or "transcript"
    invalid = '<>:"/\\|?*'
    return "".join("_" if char in invalid else char for char in stem)


def format_timestamp(seconds: float) -> str:
    total_milliseconds = int(round(seconds * 1000))
    whole = total_milliseconds // 1000
    milliseconds = total_milliseconds % 1000
    hours = whole // 3600
    minutes = (whole % 3600) // 60
    secs = whole % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{milliseconds:03d}"


def format_duration(seconds: float) -> str:
    return str(timedelta(seconds=int(round(seconds))))


if __name__ == "__main__":
    raise SystemExit(main())
