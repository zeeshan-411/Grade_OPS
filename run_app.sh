#!/usr/bin/env bash
# Launch the GradeOps Streamlit frontend.
# Handles: port collision, iCloud-dataless project files (incl. PDFs), finding the venv.

set -e
cd "$(dirname "$0")"

VENV="$HOME/Library/Caches/gradeops-venv"
if [[ ! -x "$VENV/bin/streamlit" ]]; then
  echo "❌ Streamlit not found at $VENV/bin/streamlit"
  echo "   Recreate the venv with:"
  echo "     python3 -m venv \"$VENV\""
  echo "     \"$VENV/bin/pip\" install -r gradeops/requirements.txt"
  exit 1
fi

# Pre-warm any iCloud-dataless project files so reads inside the app don't hang.
# (3 passes because macOS sometimes re-evicts mid-batch.)
# Includes PDFs / CSVs because the sample-data buttons read them via p.read_bytes().
echo "📂 Materializing project files (warming iCloud-evicted files)…"
for pass in 1 2 3; do
  find . -path ./.venv -prune -o -path ./.git -prune -o -type f \
    \( -name "*.py" -o -name "*.json" -o -name "*.csv" -o -name "*.txt" \
       -o -name "*.md" -o -name "*.pdf" -o -name ".env" \) -print 2>/dev/null \
    | while read -r f; do cat "$f" > /dev/null 2>&1; done
done

# Free port 8501 if a previous run left a process behind
if lsof -ti:8501 >/dev/null 2>&1; then
  echo "⚠️  Port 8501 in use — killing previous streamlit process"
  lsof -ti:8501 | xargs kill -9 2>/dev/null || true
fi

echo "🚀 Launching at http://localhost:8501"
exec "$VENV/bin/streamlit" run app.py "$@"
