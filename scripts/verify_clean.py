"""Reproduce from source in an isolated temporary copy; no cached PDF/binaries."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="ghostchip-clean-") as temp:
    target = Path(temp) / "source"
    shutil.copytree(root, target, ignore=shutil.ignore_patterns(
        ".git", ".venv", ".venv-wsl", "__pycache__", "artifacts", "datasheet.pdf",
        "node_modules", ".next", "out", ".playwright-cli", "output"))
    commands = [
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        [sys.executable, "-m", "ghostchip.proof"],
    ]
    commands.extend([sys.executable, "-m", "ghostchip.real_driver", "--case", case]
                    for case in ("init_ok", "wrong_chip_id", "chip_id_bus_error",
                                 "calibration_bus_error", "humidity_x4",
                                 "humidity_x4_no_latch", "reset_after_configuration"))
    for command in commands:
        subprocess.run(command, cwd=target, check=True, timeout=90)
print("Clean-source reproduction passed; vendored Bosch core rebuilt and optional vendor PDFs intentionally absent.")
