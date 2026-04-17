#!/bin/bash
set -e

cd "$(dirname "$0")"

if ! command -v python3 &>/dev/null; then
  echo "Python3 requis"
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "Création de l'environnement virtuel..."
  python3 -m venv .venv
fi

source .venv/bin/activate

echo "Installation des dépendances..."
pip install -q -r requirements.txt

echo ""
echo "✅ Event Intel démarré → http://localhost:8000"
echo "   Ctrl+C pour arrêter"
echo ""

cd backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
