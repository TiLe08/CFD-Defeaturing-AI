@echo off
chcp 65001 >nul
rem Rechnet den vollen F1-Datensatz (Kanal, ca. 500 Faelle, alle Feature-Typen) und erstellt den Bericht.
echo === F1-Datensatz rechnen (ca. 20-40 Minuten)
echo Das Fenster offen lassen, bis FERTIG erscheint.
echo Abbrechen mit Strg+C ist moeglich; ein neuer Start rechnet nur, was fehlt.
echo.
wsl -d Ubuntu-24.04 --cd "%~dp0.." -- bash -c "tr -d '\r' < scripts/run_design.sh > /tmp/fad_design.sh && bash /tmp/fad_design.sh f1_alle"
echo.
pause
