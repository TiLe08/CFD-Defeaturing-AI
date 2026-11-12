# Anleitung für Windows: vom leeren Laptop zum ersten Ergebnis

Du brauchst dafür nur Doppelklicks und einmal ein Passwort. Insgesamt dauert es etwa 30–45 Minuten, das meiste davon ist Warten. Du machst das nur einmal. Später reicht Schritt 3.

Was im Hintergrund passiert: OpenFOAM läuft nur unter Linux. Windows bringt dafür „WSL“ mit, ein Ubuntu-Linux, das innerhalb von Windows läuft. Die Skripte installieren WSL, darin OpenFOAM und Python, und rechnen dann die 14 Fälle des Machbarkeitsnachweises.

## Schritt 0: Dateien herunterladen

1. Die ZIP-Datei `CFD-Start-Windows.zip` aus dem Projekt herunterladen. Alternativ auf https://github.com/TiLe08/CFD-Defeaturing-AI auf den grünen Knopf **Code** und dann **Download ZIP** klicken.
2. Rechtsklick auf die ZIP-Datei, **Alle extrahieren…**, als Ziel z. B. `Dokumente` wählen.
3. Den entpackten Ordner öffnen und darin den Ordner `windows`. Dort liegen die Dateien `1_WSL_installieren`, `2_Einrichten`, `3_AP2_rechnen`, `4_Defeaturing_Tool` und `5_F1_Datensatz_rechnen`.

Falls Windows beim Doppelklick „Der Computer wurde durch Windows geschützt“ meldet: auf **Weitere Informationen** und dann **Trotzdem ausführen** klicken. Die Skripte sind kurz und stehen offen im Repo.

## Schritt 1: WSL installieren (einmalig, mit Neustart)

1. Doppelklick auf `1_WSL_installieren`.
2. Die Frage „Möchten Sie zulassen, dass…“ mit **Ja** beantworten.
3. Warten, bis im Fenster „Computer NEU STARTEN“ steht. Eine Taste drücken, dann den Computer neu starten.
4. Nach dem Neustart öffnet sich ein schwarzes Ubuntu-Fenster. Falls nicht: im Startmenü „Ubuntu 24.04“ suchen und anklicken.
5. Ubuntu fragt nach einem Benutzernamen: z. B. `tim` eingeben (klein, ohne Leerzeichen), Enter.
6. Dann nach einem Passwort, zweimal. **Beim Tippen erscheinen keine Zeichen, das ist normal.** Ein einfaches Passwort reicht, aber merk es dir.
7. Wenn eine Zeile wie `tim@ANTIKYTHERA_1:~$` erscheint, ist Ubuntu fertig. Das Fenster kannst du schließen.

## Schritt 2: Einrichten (einmalig, ca. 15–20 Minuten)

1. Doppelklick auf `2_Einrichten`.
2. Wenn `[sudo] password for tim:` erscheint: das Ubuntu-Passwort aus Schritt 1 eintippen (wieder unsichtbar), Enter.
3. Warten. Am längsten dauert „OpenFOAM … das dauert einige Minuten“.
4. Am Ende steht `FERTIG. OpenFOAM-Version: v…, Python-Tests bestanden.` Dann eine Taste drücken.

## Schritt 3: Machbarkeitsnachweis rechnen (wenige Minuten)

1. Doppelklick auf `3_AP2_rechnen`.
2. Warten, bis `FERTIG` erscheint. Danach öffnet sich ein Ordner `CFD-Ergebnisse` in deinem Benutzerordner.
3. Die Datei `fuer_claude.txt` aus diesem Ordner an Claude schicken (hochladen oder den Inhalt kopieren).

Schritt 3 kannst du jederzeit wiederholen. Er holt sich automatisch den neuesten Code und rechnet nur, was noch fehlt.

## Schritt 4: Defeaturing-Tool (STL prüfen und bereinigen)

1. Doppelklick auf `4_Defeaturing_Tool`. Beim ersten Start werden noch ein paar Pakete installiert (ca. 1 Minute).
2. Der Browser öffnet sich mit dem Tool. Das schwarze Fenster offen lassen, solange du das Tool benutzt.
3. Links die STL hineinziehen und die Einheit angeben, dann **Features suchen**. Zum Ausprobieren gibt es **Beispielplatte laden**.
4. Im Bild auf ein Feature klicken schaltet zwischen grün (entfernen) und rot (behalten) um.
5. **STL + Protokoll herunterladen.** Eine Kopie landet zusätzlich im Ordner `CFD-Ergebnisse\Defeaturing` in deinem Benutzerordner.
6. Fertig? Das schwarze Fenster schließen.

Mehr dazu, auch zu den Grenzen: `docs/defeaturing_tool.md`.

## Schritt 5: F1-Datensatz rechnen (ca. 10–20 Minuten)

Das ist der volle Datensatz für die Kanal-Familie F1 (etwa 310 Rechnungen), aus dem später das Modell lernt.

1. Doppelklick auf `5_F1_Datensatz_rechnen`.
2. Das Fenster offen lassen, bis `FERTIG` erscheint. Danach öffnet sich ein Ordner `CFD-Ergebnisse\f1_<Datum>`.
3. Aus diesem Ordner die beiden Dateien `fuer_claude.txt` und `dataset_f1.parquet` an Claude schicken.

Abbrechen geht jederzeit (Fenster schließen). Ein neuer Doppelklick rechnet nur, was noch fehlt.

## Wenn etwas schiefgeht

Schick Claude einfach den Text aus dem Fenster: mit der Maus markieren, Strg+C, im Chat einfügen. Ein Foto vom Bildschirm geht auch. Häufige Fälle:

| Meldung | Bedeutung | Lösung |
| --- | --- | --- |
| `0x80370102` oder „Virtualisierung“ | Virtualisierung ist im BIOS ausgeschaltet | Claude fragen, Anleitung für dein Gerät folgt |
| `Ubuntu-24.04 not found` / „Es gibt keine Distribution“ | Schritt 1 ist nicht fertig | Schritt 1 wiederholen, Neustart nicht vergessen |
| `Sorry, try again.` | Passwort falsch getippt | Langsam neu eingeben |
| `FEHLER: Kein OpenFOAM-Paket gefunden` | Paketquelle von openfoam.com nicht erreichbar | Text an Claude schicken |

## Die Ergebnisse ansehen (optional)

Die gerechneten Fälle liegen in Ubuntu unter `~/CFD-Defeaturing-AI/data/raw`. Im Windows-Explorer erreichst du sie, indem du in die Adresszeile `\\wsl$\Ubuntu-24.04\home\` eingibst. Jeder Fallordner enthält eine Datei `case.foam`, die du in ParaView öffnen kannst.
