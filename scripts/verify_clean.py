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
        ".git", ".venv", ".venv-wsl", "__pycache__", "artifacts", "datasheet.pdf"))
    for command in ([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                    [sys.executable, "-m", "ghostchip.proof"]):
        subprocess.run(command, cwd=target, check=True, timeout=60)
print("Clean-source reproduction passed; optional vendor PDF intentionally absent.")
