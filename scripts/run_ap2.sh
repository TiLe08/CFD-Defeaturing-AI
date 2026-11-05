#!/usr/bin/env bash
# AP2 komplett: Code aktualisieren, Rauchtest, 14 Fälle, Gate-1-Auswertung.
# Wird von windows/3_AP2_rechnen.bat aufgerufen. Abbrechen ist jederzeit
# möglich; ein erneuter Start rechnet nur, was noch fehlt.
set -euo pipefail

REPO_DIR="$HOME/CFD-Defeaturing-AI"
ENV_FILE="$HOME/.fad_env"
[ -f "$ENV_FILE" ] || { echo "Bitte zuerst 2_Einrichten.bat ausführen."; exit 1; }
# shellcheck disable=SC1090
source "$ENV_FILE"
cd "$REPO_DIR"
git pull --ff-only -q || echo "(Hinweis: Code konnte nicht aktualisiert werden, rechne mit dem vorhandenen Stand)"
PY=.venv/bin/python
NO_FO_FLAG=""
[ "${FAD_NO_FO:-0}" = "1" ] && NO_FO_FLAG="--no-function-objects"  # nur für Tests

echo "=== Rauchtest: ein Fall"
$PY -m pipeline.sweep --design ap2 --plan-only >/dev/null
$PY -m cfd.run_case data/raw/f1_ap2_b000_without $NO_FO_FLAG
SMOKE="data/raw/f1_ap2_b000_without/result.json"
if [ ! -f "$SMOKE" ]; then
    echo "FEHLER im Rauchtest. Bitte den Ordner data/raw/f1_ap2_b000_without an Claude schicken."
    exit 1
fi

echo "=== Alle 14 Fälle mit $FAD_WORKERS Workern"
$PY -m pipeline.sweep --design ap2 --workers "$FAD_WORKERS" $NO_FO_FLAG

echo "=== Gate-1-Auswertung"
$PY -m pipeline.ap2_report --workers "$FAD_WORKERS" --planned-runs 900 >/dev/null

# Ergebnisse für Windows und für Claude zusammenstellen
WIN_HOME=""
if command -v cmd.exe >/dev/null 2>&1; then
    WIN_HOME="$(wslpath "$(cmd.exe /c 'echo %USERPROFILE%' 2>/dev/null | tr -d '\r')" 2>/dev/null || true)"
fi
OUT="${WIN_HOME:-$HOME}/CFD-Ergebnisse/ap2_$(date +%Y-%m-%d_%H%M)"
mkdir -p "$OUT"
cp data/raw/ap2_summary.md data/raw/ap2_features.csv "$OUT/"
{
    echo "Für Claude (Inhalt in den Chat kopieren oder Datei hochladen)"
    echo
    echo "OpenFOAM: $(bash -c "source '$FOAM_BASHRC' >/dev/null 2>&1; echo \$WM_PROJECT_VERSION")"
    echo "Code-Stand: $(git rev-parse --short HEAD)"
    echo "Worker: $FAD_WORKERS"
    echo
    echo "Rauchtest result.json:"
    cat "$SMOKE"
    echo
    cat data/raw/ap2_summary.md
} > "$OUT/fuer_claude.txt"
# Logs der fehlgeschlagenen Fälle mitnehmen
for st in data/raw/*/status.json; do
    if grep -q '"state": "failed"' "$st"; then
        d="$(dirname "$st")"
        mkdir -p "$OUT/fehler/$(basename "$d")"
        cp "$d"/status.json "$d"/log.* "$OUT/fehler/$(basename "$d")/" 2>/dev/null || true
    fi
done

echo
echo "FERTIG. Ergebnisse liegen in:"
if [ -n "$WIN_HOME" ]; then
    wslpath -w "$OUT"
    explorer.exe "$(wslpath -w "$OUT")" || true
else
    echo "$OUT"
fi
echo "Bitte die Datei fuer_claude.txt an Claude schicken."
