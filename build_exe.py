"""Build the Windows executable.

    python build_exe.py

Produces dist/IGprepper.exe as a single file. The source itself is
cross-platform; only Windows gets a packaged binary, so this refuses to run
elsewhere rather than quietly producing something untested.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

APP_NAME = "IGprepper"
ROOT = Path(__file__).parent

# PySide6 ships far more than a small app needs, and the unused Qt modules
# dominate the binary size.
EXCLUDES = [
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtMultimedia", "PySide6.QtNetwork", "PySide6.Qt3DCore",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtSql",
    "PySide6.QtTest", "PySide6.QtPdf", "PySide6.QtBluetooth",
    "tkinter", "unittest", "pytest", "numpy", "scipy",
]


def main() -> int:
    if sys.platform != "win32":
        print(
            "This builds the Windows executable only.\n"
            "On macOS and Linux, run the app from source: python -m igprep",
            file=sys.stderr,
        )
        return 1

    if shutil.which("pyinstaller") is None:
        print(
            "pyinstaller not found. Install the dev requirements first:\n"
            "    pip install -r requirements-dev.txt",
            file=sys.stderr,
        )
        return 1

    for stale in (ROOT / "build", ROOT / "dist"):
        shutil.rmtree(stale, ignore_errors=True)

    command = [
        "pyinstaller",
        "--name", APP_NAME,
        "--onefile",
        "--windowed",          # no console window behind the GUI
        "--noconfirm",
        "--clean",
        "--paths", str(ROOT),
        "--collect-submodules", "igprep",
    ]
    for module in EXCLUDES:
        command += ["--exclude-module", module]
    # app.py, not igprep/__main__.py: PyInstaller runs the entry script as a
    # top-level module, where __main__.py's relative imports have no package.
    command.append(str(ROOT / "app.py"))

    print(" ".join(command), "\n")
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        return result.returncode

    exe = ROOT / "dist" / f"{APP_NAME}.exe"
    if exe.exists():
        print(f"\nBuilt {exe}  ({exe.stat().st_size / 1_048_576:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
