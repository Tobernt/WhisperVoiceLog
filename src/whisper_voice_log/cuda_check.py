from __future__ import annotations

import ctypes
import shutil
import subprocess
from pathlib import Path

from .cuda_paths import add_cuda_dll_directories


REQUIRED_DLLS = ("cudart64_12.dll", "cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll")


def main() -> int:
    added = add_cuda_dll_directories()
    print("NVIDIA DLL directories:")
    for path in added:
        print(f"  {path}")
    if not added:
        print("  none found")

    print("")
    print("DLL load check:")
    failures = 0
    for dll in REQUIRED_DLLS:
        try:
            ctypes.WinDLL(dll)
            print(f"  OK {dll}")
        except OSError as exc:
            failures += 1
            found = shutil.which(dll)
            hint = f" found at {found}" if found else " not found on PATH"
            print(f"  FAIL {dll}:{hint}; {exc}")

    print("")
    print("nvidia-smi:")
    try:
        output = subprocess.check_output(["nvidia-smi"], text=True, stderr=subprocess.STDOUT)
        first_lines = "\n".join(output.splitlines()[:12])
        print(first_lines)
    except Exception as exc:
        failures += 1
        print(f"  FAIL {exc}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
