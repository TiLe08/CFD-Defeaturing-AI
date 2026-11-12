#!/usr/bin/env bash
# Startet das Defeaturing-Tool (Stufe 1) und öffnet es im Browser.
# Wird von windows/4_Defeaturing_Tool.bat aufgerufen. Fenster offen lassen,
# solange das Tool benutzt wird; Schließen beendet das Tool.
set -euo pipefail

REPO_DIR="$HOME/CFD-Defeaturing-AI"
PORT="${FAD_PORT:-8765}"
URL="http://localhost:$PORT"
[ -d "$REPO_DIR/.venv" ] || { echo "Bitte zuerst 2_Einrichten.bat ausführen."; exit 1; }
cd "$REPO_DIR"
git pull --ff-only -q 2>/dev/null || echo "(Hinweis: Code konnte nicht aktualisiert werden, starte mit dem vorhandenen Stand)"
PY=.venv/bin/python

# fehlende Pakete nachinstallieren (beim ersten Start nach einem Update)
if ! $PY -c "import fastapi, uvicorn, multipart, manifold3d" 2>/dev/null; then
    echo "=== Installiere Pakete für das Tool (einmalig, ca. 1 Minute)"
    .venv/bin/pip install -q -r env/requirements.txt
fi

open_browser() {
    if command -v cmd.exe >/dev/null 2>&1; then
        cmd.exe /c start "" "$URL" >/dev/null 2>&1 || true
    else
        xdg-open "$URL" >/dev/null 2>&1 || true
    fi
}

if curl -fs "$URL/api/version" >/dev/null 2>&1; then
    echo "Das Tool läuft schon, öffne den Browser."
    open_browser
    exit 0
fi

# Exporte zusätzlich in den Windows-Benutzerordner legen
WIN_HOME=""
if command -v cmd.exe >/dev/null 2>&1; then
    WIN_HOME="$(wslpath "$(cmd.exe /c 'echo %USERPROFILE%' 2>/dev/null | tr -d '\r')" 2>/dev/null || true)"
fi
OUT="${WIN_HOME:-$HOME}/CFD-Ergebnisse/Defeaturing"
export FAD_OUTPUT_DIR="$OUT"
if [ -n "$WIN_HOME" ]; then
    export FAD_OUTPUT_DIR_DISPLAY="$(wslpath -w "$OUT" 2>/dev/null || echo "$OUT")"
fi

$PY -m app.server --port "$PORT" &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true' EXIT
for _ in $(seq 1 60); do
    curl -fs "$URL/api/version" >/dev/null 2>&1 && break
    sleep 0.5
done
open_browser
echo
echo "Das Tool ist offen: $URL"
echo "Ergebnisse werden außerdem gespeichert in: ${FAD_OUTPUT_DIR_DISPLAY:-$OUT}"
echo "Zum Beenden dieses Fenster schließen."
wait $SERVER
