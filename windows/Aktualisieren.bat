@echo off
chcp 65001 >nul
rem Holt den neuesten Stand von GitHub: in diesen Ordner und in Ubuntu (WSL).
rem Veraenderte Code-Dateien werden ueberschrieben, eigene neue Dateien und
rem Rechenergebnisse (data\, CFD-Ergebnisse) bleiben erhalten.
echo === Aktualisieren: neuesten Stand von GitHub holen
echo.
set "REPO=https://github.com/TiLe08/CFD-Defeaturing-AI.git"
pushd "%~dp0.."
where git >nul 2>&1
if %errorlevel% neq 0 (
    echo Git fuer Windows ist nicht installiert, dieser Ordner wird uebersprungen.
    echo Installieren: https://git-scm.com/download/win
    goto wsl
)
if not exist ".git" (
    echo Dieser Ordner ist noch nicht mit GitHub verbunden, verbinde ihn jetzt ...
    git init -q -b main
    git remote add origin "%REPO%"
)
git -c http.sslBackend=schannel fetch -q origin main
if %errorlevel% neq 0 (
    echo FEHLER: GitHub nicht erreichbar. Internetverbindung pruefen.
    goto wsl
)
git checkout -q -f -B main origin/main
git branch -q -u origin/main >nul 2>&1
echo Windows-Ordner ist aktuell:
git log --oneline -1

:wsl
popd
echo.
wsl -d Ubuntu-24.04 -- bash -c "test -d ~/CFD-Defeaturing-AI/.git" >nul 2>&1
if %errorlevel% neq 0 (
    echo Ubuntu ist noch nicht eingerichtet: bitte 2_Einrichten.bat ausfuehren.
    goto ende
)
wsl -d Ubuntu-24.04 -- bash -c "cd ~/CFD-Defeaturing-AI && git fetch -q origin main && git checkout -q -f main && git reset -q --hard origin/main && echo Ubuntu-Ordner ist aktuell: && git log --oneline -1"
if %errorlevel% neq 0 echo FEHLER beim Aktualisieren in Ubuntu. Den Text bitte an Claude schicken.

:ende
echo.
echo FERTIG.
pause
