@echo off
chcp 65001 >nul
rem Installiert OpenFOAM, Python-Pakete und den Code in Ubuntu (WSL).
echo === Schritt 2: Einrichten (ca. 10-20 Minuten)
echo Wenn nach dem Passwort gefragt wird: das Ubuntu-Passwort aus Schritt 1 eingeben
echo (beim Tippen erscheinen keine Zeichen) und Enter druecken.
echo.
wsl -d Ubuntu-24.04 --cd "%~dp0.." -- bash -c "tr -d '\r' < scripts/setup_wsl.sh > /tmp/fad_setup.sh && bash /tmp/fad_setup.sh"
echo.
echo Wenn oben FERTIG steht, weiter mit 3_AP2_rechnen.bat.
echo Wenn ein FEHLER steht: den Text im Fenster markieren, kopieren und an Claude schicken.
pause
