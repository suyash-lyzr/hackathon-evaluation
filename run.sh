#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate

pip install -q --upgrade pip
pip install -q -r requirements.txt

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo ""
  echo "⚠️  .env created from template. Edit it with your DB_URL + OPENAI_API_KEY, then re-run ./run.sh"
  exit 1
fi

# Regenerate sample xlsx on every boot (cheap, keeps it fresh)
python -m backend.make_sample

PORT="${PORT:-8010}"
echo ""
echo "▶  Hackathon Evaluation running at http://localhost:${PORT}"
echo ""
exec uvicorn backend.main:app --host 0.0.0.0 --port "${PORT}" --reload
