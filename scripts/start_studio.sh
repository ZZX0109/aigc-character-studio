#!/bin/sh
set -eu
STUDIO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$STUDIO_ROOT"
if [ ! -x .venv/bin/python ]; then
  printf '%s\n' '请先按 README 安装项目依赖。'
  exit 1
fi
if [ ! -f frontend/dist/index.html ]; then
  (cd frontend && npm run build)
fi
export PYTHONPATH="$STUDIO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
printf '%s\n' 'AIGC Character Studio: http://127.0.0.1:8765'
exec .venv/bin/python -m uvicorn character_studio.api:app --host 127.0.0.1 --port 8765
