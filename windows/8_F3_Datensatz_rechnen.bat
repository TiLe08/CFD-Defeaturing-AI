@echo off
chcp 65001 >nul
rem Rechnet den vollen F3-Datensatz (Einlass-Port, turbulent, ca. 250 Faelle, alle Feature-Typen) und erstellt den Bericht.
echo === F3-Datensatz rechnen (ca. 30-60 Minuten)
echo Das Fenster offen lassen, bis FERTIG erscheint.
echo Abbrechen mit Strg+C ist moeglich; ein neuer Start rechnet nur, was fehlt.
echo.
wsl -d Ubuntu-24.04 --cd "%~dp0.." -- bash -c "tr -d '\r' < scripts/run_design.sh > /tmp/fad_design.sh && bash /tmp/fad_design.sh f3"
echo.
pause
