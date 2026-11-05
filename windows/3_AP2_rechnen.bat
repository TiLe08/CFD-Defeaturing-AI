@echo off
chcp 65001 >nul
rem Rechnet den Machbarkeitsnachweis AP2 (14 Faelle) und erstellt die Auswertung.
echo === Schritt 3: AP2 rechnen (wenige Minuten)
echo Das Fenster darf offen bleiben, bis FERTIG erscheint.
echo Abbrechen mit Strg+C ist moeglich; ein neuer Start rechnet nur, was fehlt.
echo.
wsl -d Ubuntu-24.04 --cd "%~dp0.." -- bash -c "tr -d '\r' < scripts/run_ap2.sh > /tmp/fad_run.sh && bash /tmp/fad_run.sh"
echo.
pause
