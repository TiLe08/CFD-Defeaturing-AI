@echo off
chcp 65001 >nul
rem LLM-Auswertung L0/L1 mit Ollama auf der Grafikkarte (beim ersten Mal ca. 5 GB Download).
echo === LLM auswerten (ca. 2-4 Stunden)
echo Das Fenster offen lassen, bis FERTIG erscheint.
echo Abbrechen mit Strg+C ist moeglich; ein neuer Start macht dort weiter.
echo.
wsl -d Ubuntu-24.04 --cd "%~dp0.." -- bash -c "tr -d '\r' < scripts/run_llm.sh > /tmp/fad_llm.sh && bash /tmp/fad_llm.sh"
echo.
pause
