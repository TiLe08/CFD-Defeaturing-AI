@echo off
chcp 65001 >nul
rem Rechnet den vollen F2-Datensatz (Verteiler, ca. 210 Faelle) und erstellt den Bericht.
echo === F2-Datensatz rechnen (ca. 10-20 Minuten)
echo Das Fenster offen lassen, bis FERTIG erscheint.
echo Abbrechen mit Strg+C ist moeglich; ein neuer Start rechnet nur, was fehlt.
echo.
wsl -d Ubuntu-24.04 --cd "%~dp0.." -- bash -c "tr -d '\r' < scripts/run_design.sh > /tmp/fad_design.sh && bash /tmp/fad_design.sh f2"
echo.
pause
