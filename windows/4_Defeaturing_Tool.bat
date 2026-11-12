@echo off
chcp 65001 >nul
rem Startet das Defeaturing-Tool im Browser (STL rein, Features pruefen, STL raus).
echo === Defeaturing-Tool
echo Der Browser oeffnet sich gleich von selbst.
echo Dieses Fenster offen lassen, solange du das Tool benutzt. Schliessen beendet das Tool.
echo.
wsl -d Ubuntu-24.04 -- bash -c "cd ~/CFD-Defeaturing-AI && git pull --ff-only -q; tr -d '\r' < scripts/run_tool.sh > /tmp/fad_tool.sh && bash /tmp/fad_tool.sh"
echo.
echo Wenn ein FEHLER steht: den Text im Fenster markieren, kopieren und an Claude schicken.
pause
