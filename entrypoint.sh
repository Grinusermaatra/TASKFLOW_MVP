#!/bin/sh
set -eu

if [ "${SEED_ON_STARTUP:-0}" = "1" ]; then
  python seed.py
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
