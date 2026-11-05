#!/usr/bin/env bash
# Einrichtung in WSL/Ubuntu: OpenFOAM (ESI), Python-Umgebung, Code.
# Wird von windows/2_Einrichten.bat aufgerufen; kann beliebig oft laufen.
set -euo pipefail

REPO_URL="https://github.com/TiLe08/CFD-Defeaturing-AI.git"
REPO_DIR="$HOME/CFD-Defeaturing-AI"
ENV_FILE="$HOME/.fad_env"

say() { printf '\n=== %s\n' "$*"; }

say "Schritt 1/5: Ubuntu-Pakete (Passwort deines Ubuntu-Benutzers wird abgefragt)"
sudo apt-get update -qq
sudo apt-get install -y -qq git curl python3 python3-venv python3-pip ca-certificates >/dev/null

find_bashrc() {
    ls -d /usr/lib/openfoam/openfoam*/etc/bashrc 2>/dev/null | sort -V | tail -1
}

say "Schritt 2/5: OpenFOAM (ESI, openfoam.com)"
BASHRC="$(find_bashrc || true)"
if [ -z "$BASHRC" ]; then
    curl -fsSL https://dl.openfoam.com/add-debian-repo.sh | sudo bash
    sudo apt-get update -qq
    PKG="$(apt-cache search --names-only '^openfoam2[0-9]{3}-default$' | awk '{print $1}' | sort -V | tail -1)"
    if [ -z "$PKG" ]; then
        echo "FEHLER: Kein OpenFOAM-Paket gefunden. Bitte die Ausgabe an Claude schicken."
        exit 1
    fi
    echo "Installiere $PKG (das dauert einige Minuten) ..."
    sudo apt-get install -y -qq "$PKG" >/dev/null
    BASHRC="$(find_bashrc)"
fi
echo "OpenFOAM: $BASHRC"

say "Schritt 3/5: Code von GitHub"
if [ -d "$REPO_DIR/.git" ]; then
    git -C "$REPO_DIR" pull --ff-only
else
    git clone "$REPO_URL" "$REPO_DIR"
fi

say "Schritt 4/5: Python-Umgebung"
cd "$REPO_DIR"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r env/requirements.txt

# Physische Kerne minus 1 (Hyperthreads helfen bei CFD kaum)
CORES="$(lscpu -p=Core,Socket | grep -v '^#' | sort -u | wc -l)"
WORKERS=$(( CORES > 1 ? CORES - 1 : 1 ))
cat > "$ENV_FILE" <<EOT
export FOAM_BASHRC="$BASHRC"
export FAD_WORKERS="$WORKERS"
EOT
echo "Einstellungen gespeichert in $ENV_FILE (Worker: $WORKERS)"

say "Schritt 5/5: Selbsttest"
.venv/bin/python -m pytest -q
OF_VERSION="$(bash -c "source '$BASHRC' >/dev/null 2>&1; echo \$WM_PROJECT_VERSION")"
echo
echo "FERTIG. OpenFOAM-Version: $OF_VERSION, Python-Tests bestanden."
echo "Als Nächstes: 3_AP2_rechnen.bat doppelklicken."
