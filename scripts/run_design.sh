#!/usr/bin/env bash
# Rechnet einen Versuchsplan (z. B. f1) und erstellt den Datensatz-Bericht.
# Aufruf: bash scripts/run_design.sh f1
# Wird von windows/5_F1_Datensatz_rechnen.bat aufgerufen. Abbrechen ist jederzeit
# möglich; ein erneuter Start rechnet nur, was noch fehlt.
set -euo pipefail

DESIGN="${1:?Versuchsplan angeben, z. B. f1}"
REPO_DIR="$HOME/CFD-Defeaturing-AI"
ENV_FILE="$HOME/.fad_env"
[ -f "$ENV_FILE" ] || { echo "Bitte zuerst 2_Einrichten.bat ausführen."; exit 1; }
# shellcheck disable=SC1090
source "$ENV_FILE"
cd "$REPO_DIR"
git pull --ff-only -q || echo "(Hinweis: Code konnte nicht aktualisiert werden, rechne mit dem vorhandenen Stand)"
.venv/bin/pip install -q -r env/requirements.txt
case "$DESIGN" in f2*)
    # gmsh braucht ein paar Grafik-Bibliotheken (einmalig, fragt das Ubuntu-Passwort ab)
    if ! ldconfig -p | grep -q libGLU.so.1; then
        echo "=== Einmalig: Zusatzpakete für gmsh installieren"
        sudo apt-get install -y -qq libglu1-mesa libxcursor1 libxinerama1 libxft2 \
            libxrender1 libxfixes3 >/dev/null
    fi ;;
esac
PY=.venv/bin/python
NO_FO_FLAG=""
[ "${FAD_NO_FO:-0}" = "1" ] && NO_FO_FLAG="--no-function-objects"  # nur für Tests

echo "=== Versuchsplan $DESIGN mit $FAD_WORKERS Workern"
$PY -m pipeline.sweep --design "$DESIGN" --workers "$FAD_WORKERS" $NO_FO_FLAG

echo "=== Datensatz-Bericht"
$PY -m pipeline.dataset_report --design "$DESIGN" >/dev/null

WIN_HOME=""
if command -v cmd.exe >/dev/null 2>&1; then
    WIN_HOME="$(wslpath "$(cmd.exe /c 'echo %USERPROFILE%' 2>/dev/null | tr -d '\r')" 2>/dev/null || true)"
fi
OUT="${WIN_HOME:-$HOME}/CFD-Ergebnisse/${DESIGN}_$(date +%Y-%m-%d_%H%M)"
mkdir -p "$OUT"
cp "data/raw/dataset_${DESIGN}.md" "data/processed/dataset_${DESIGN}.parquet" "$OUT/"
{
    echo "Für Claude (Datei hochladen)"
    echo
    echo "OpenFOAM: $(bash -c "source '$FOAM_BASHRC' >/dev/null 2>&1; echo \$WM_PROJECT_VERSION")"
    echo "Code-Stand: $(git rev-parse --short HEAD)"
    echo "Worker: $FAD_WORKERS"
    echo
    cat "data/raw/dataset_${DESIGN}.md"
} > "$OUT/fuer_claude.txt"
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
echo "Bitte die Dateien fuer_claude.txt und dataset_${DESIGN}.parquet an Claude schicken."
