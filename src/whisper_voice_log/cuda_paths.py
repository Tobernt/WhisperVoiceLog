from __future__ import annotations

import os
import site
import sys
from pathlib import Path


_DLL_HANDLES: list[object] = []


def add_cuda_dll_directories() -> list[Path]:
    """Add project-local NVIDIA wheel DLL folders to the Windows loader path."""
    if os.name != "nt":
        return []

    added: list[Path] = []
    roots: list[Path] = []

    for path in site.getsitepackages():
        roots.append(Path(path))

    try:
        roots.append(Path(site.getusersitepackages()))
    except Exception:
        pass

    for raw_path in sys.path:
        if raw_path:
            roots.append(Path(raw_path))

    for root in dict.fromkeys(roots):
        nvidia_root = root / "nvidia"
        if not nvidia_root.exists():
            continue

        for bin_dir in sorted(nvidia_root.glob("*/bin")):
            if not bin_dir.is_dir() or not any(bin_dir.glob("*.dll")):
                continue

            path_text = str(bin_dir)
            if path_text not in os.environ.get("PATH", ""):
                os.environ["PATH"] = path_text + os.pathsep + os.environ.get("PATH", "")

            try:
                _DLL_HANDLES.append(os.add_dll_directory(path_text))
            except (FileNotFoundError, OSError):
                continue

            added.append(bin_dir)

    return added
