#!/usr/bin/env bash
set -euo pipefail

demo_venv="$HOME/.cache/ghostchip-demo-venv"
if [ ! -x "$demo_venv/bin/python" ]; then
  python3 -m venv "$demo_venv"
fi

requirements_hash=$(sha256sum requirements.txt | cut -d' ' -f1)
installed_hash=$(cat "$demo_venv/.ghostchip-requirements" 2>/dev/null || true)
if [ "$requirements_hash" != "$installed_hash" ]; then
  "$demo_venv/bin/python" -m pip install -r requirements.txt
  printf '%s' "$requirements_hash" > "$demo_venv/.ghostchip-requirements"
fi

exec "$demo_venv/bin/python" -m ghostchip.demo --host 0.0.0.0 --port 8765
