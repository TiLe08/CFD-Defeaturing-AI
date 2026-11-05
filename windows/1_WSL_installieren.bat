@echo off
chcp 65001 >nul
rem Installiert WSL mit Ubuntu 24.04. Braucht Administratorrechte und danach einen Neustart.
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Fordere Administratorrechte an ...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
echo.
echo === Schritt 1: WSL und Ubuntu 24.04 installieren
echo Das dauert einige Minuten. Bitte das Fenster offen lassen.
echo.
wsl --install -d Ubuntu-24.04
echo.
echo ============================================================
echo  Wenn oben ein Fehler steht: Foto oder Text an Claude schicken.
echo.
echo  Sonst: Computer NEU STARTEN.
echo  Nach dem Neustart oeffnet sich ein Ubuntu-Fenster (ggf. im
echo  Startmenue "Ubuntu 24.04" anklicken). Dort einen Benutzernamen
echo  (klein, ohne Leerzeichen) und ein Passwort festlegen.
echo  Beim Tippen des Passworts erscheinen KEINE Zeichen, das ist normal.
echo  Das Passwort gut merken, es wird in Schritt 2 gebraucht.
echo ============================================================
pause
