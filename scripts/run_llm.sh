#!/usr/bin/env bash
# LLM-Auswertung L0/L1 mit Ollama (lokal, Grafikkarte) und Vergleich mit B1/M1.
# Aufruf: bash scripts/run_llm.sh [modell]   (Standard: qwen2.5:7b)
# Wird von windows/9_LLM_auswerten.bat aufgerufen. Abbrechen ist jederzeit
# möglich; ein erneuter Start fragt nur die noch fehlenden Antworten ab.
set -euo pipefail

MODEL="${1:-qwen2.5:7b}"
REPO_DIR="$HOME/CFD-Defeaturing-AI"
ENV_FILE="$HOME/.fad_env"
[ -f "$ENV_FILE" ] || { echo "Bitte zuerst 2_Einrichten.bat ausführen."; exit 1; }
cd "$REPO_DIR"
git pull --ff-only -q || echo "(Hinweis: Code konnte nicht aktualisiert werden, rechne mit dem vorhandenen Stand)"
.venv/bin/pip install -q -r env/requirements.txt

WIN_HOME=""
if command -v cmd.exe >/dev/null 2>&1; then
    WIN_HOME="$(wslpath "$(cmd.exe /c 'echo %USERPROFILE%' 2>/dev/null | tr -d '\r')" 2>/dev/null || true)"
fi

echo "=== Datensätze suchen"
DATA="$REPO_DIR/data/llm_input"
mkdir -p "$DATA"
missing=""
for ds in f1_alle f2_alle f3 f4; do
    f="data/processed/dataset_${ds}.parquet"
    if [ ! -f "$f" ] && [ -n "$WIN_HOME" ]; then
        # sonst die neueste Kopie aus CFD-Ergebnisse (Windows)
        f="$(ls -t "$WIN_HOME"/CFD-Ergebnisse/*/dataset_${ds}.parquet 2>/dev/null | head -1 || true)"
    fi
    if [ -n "$f" ] && [ -f "$f" ]; then
        cp "$f" "$DATA/dataset_${ds}.parquet"
        echo "  $ds: $f"
    else
        missing="$missing $ds"
    fi
done
if [ -n "$missing" ]; then
    echo "FEHLER: Datensatz fehlt:$missing"
    echo "Lege die Datei(en) dataset_<name>.parquet in einen Unterordner von CFD-Ergebnisse"
    echo "in deinem Windows-Benutzerordner und starte das Skript neu."
    exit 1
fi

echo "=== Ollama"
if ! command -v ollama >/dev/null 2>&1; then
    echo "Einmalig: Ollama installieren (fragt das Ubuntu-Passwort ab)"
    sudo apt-get install -y -qq zstd >/dev/null
    curl -fsSL https://ollama.com/install.sh | sh
fi
if ! curl -sf http://127.0.0.1:11434/api/tags >/dev/null; then
    nohup ollama serve > "$HOME/.ollama_serve.log" 2>&1 &
    for _ in $(seq 1 30); do
        curl -sf http://127.0.0.1:11434/api/tags >/dev/null && break
        sleep 1
    done
fi
curl -sf http://127.0.0.1:11434/api/tags >/dev/null || { echo "FEHLER: Ollama startet nicht, siehe ~/.ollama_serve.log"; exit 1; }
echo "Modell $MODEL laden (beim ersten Mal ca. 5 GB Download)"
ollama pull "$MODEL"

echo "=== LLM-Auswertung (ca. 4300 Abfragen, auf der Grafikkarte etwa 2-4 Stunden)"
OUT_LOCAL="results/ap6_llm"
.venv/bin/python -m models.llm --data "$DATA" --out "$OUT_LOCAL" --model "$MODEL"

OUT="${WIN_HOME:-$HOME}/CFD-Ergebnisse/llm_$(date +%Y-%m-%d_%H%M)"
mkdir -p "$OUT"
cp "$OUT_LOCAL"/auswertung_llm.md "$OUT_LOCAL"/metriken_llm.csv "$OUT_LOCAL"/antworten.csv "$OUT_LOCAL"/antworten_*.jsonl "$OUT/"
{
    echo "Für Claude (Datei hochladen)"
    echo
    echo "LLM: $MODEL"
    echo "Code-Stand: $(git rev-parse --short HEAD)"
    command -v nvidia-smi >/dev/null && nvidia-smi --query-gpu=name --format=csv,noheader | sed 's/^/GPU: /'
    echo
    cat "$OUT_LOCAL/auswertung_llm.md"
} > "$OUT/fuer_claude.txt"

echo
echo "FERTIG. Ergebnisse liegen in:"
if [ -n "$WIN_HOME" ]; then
    wslpath -w "$OUT"
    explorer.exe "$(wslpath -w "$OUT")" || true
else
    echo "$OUT"
fi
echo "Bitte fuer_claude.txt und die Datei antworten_*.jsonl an Claude schicken."
