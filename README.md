# Whisper Voice Log

Local transcription for long audio/video recordings with lots of dead air.

The tool uses `faster-whisper` locally. Voice activity detection is enabled by default, so long silent sections are skipped while the output stays timestamped and grouped into a rough voice-note log.

## Setup

From PowerShell:

```powershell
cd WhisperVoiceLog
.\setup.ps1
```

The setup script creates `.venv` using Python 3.11, 3.12, or 3.10. Python 3.14 is intentionally avoided because many Whisper/PyTorch-adjacent packages do not publish stable wheels for it yet.

Install FFmpeg and add it to `PATH` for broad audio/video format support.

## Basic Use

Double-click:

```text
Launch Whisper Voice Log.bat
```

That starts the local web UI at:

```text
http://127.0.0.1:8765
```

The web UI supports drag/drop files, browser microphone recording, background jobs, transcript preview, copying output, and opening the generated Markdown file in Explorer.

Transcribe one file:

```powershell
.\transcribe.ps1 "C:\recordings\meeting.mp4"
```

Transcribe a folder recursively:

```powershell
.\transcribe.ps1 "C:\recordings" --model small --output-dir outputs
```

Use a better model when quality matters more than speed:

```powershell
.\transcribe.ps1 "C:\recordings\long-note.wav" --model medium
```

Use CUDA if you have a compatible NVIDIA GPU:

```powershell
.\setup-cuda.ps1
.\transcribe.ps1 "C:\recordings" --device cuda --compute-type float16 --model medium
```

CPU is the default because it works reliably on more Windows machines. Use `--device cuda` only after NVIDIA CUDA runtime libraries are installed and working. `setup-cuda.ps1` installs the project-local NVIDIA CUDA/cuDNN wheels and verifies the required DLLs.

## Output

For each input file, the tool writes:

- `outputs/<file>.voice-log.md`: readable Markdown with metadata, grouped voice notes, and timestamped transcript.
- `outputs/<file>.segments.json`: structured segment data for scripts and other tools.

The Markdown contains timestamped notes; the JSON preserves individual segment timings.

## Useful Options

```powershell
.\transcribe.ps1 "C:\recordings" --model small --language en
.\transcribe.ps1 "C:\recordings" --note-gap-seconds 45
.\transcribe.ps1 "C:\recordings" --max-note-minutes 12
.\transcribe.ps1 "C:\recordings" --no-vad
.\transcribe.ps1 "C:\recordings" --force
```

- `--language`: improves speed/accuracy when the language is known, for example `en` or `sv`.
- `--note-gap-seconds`: starts a new note after this much silence between speech segments.
- `--max-note-minutes`: caps each grouped voice note to a rough timeline length.
- `--no-vad`: disables dead-air skipping.
- `--force`: regenerates existing outputs.

## Model Guidance

- `tiny` or `base`: fastest, rough notes.
- `small`: good default for long voice notes.
- `medium`: better quality, slower.
- `large-v3`: best quality, much heavier.

For high-accuracy translated notes, use `large-v3`, set the spoken language when you know it, enable `Translate to English`, and use CUDA if your NVIDIA runtime is installed. On CPU, `large-v3` can be very slow for hours of audio.


## Implementation

- `src/whisper_voice_log/cli.py`: transcription, segment grouping, and output formatting.
- `src/whisper_voice_log/web.py`: FastAPI routes and background job processing.
- `web/static/`: HTML, CSS, and JavaScript interface.
- `src/whisper_voice_log/cuda_paths.py`: optional CUDA runtime discovery.

The default web server binds to `127.0.0.1`. It is intended for local use and has no account system. Models may be downloaded on first use; transcription runs locally after the model is available.

Recordings, uploaded media, generated transcripts, virtual environments, and local configuration are excluded from Git. No API key is required.
