# Defeaturing-Tool (Stufe 1)

STL rein, Features im Browser prüfen und per Klick entscheiden, bereinigte STL plus Protokoll raus. Das Tool ist die Anwendungsseite der Pipeline aus HANDOFF 3.2 und nutzt denselben Code wie die Auswertung (`stl/`, `models/`). Alles läuft lokal, es werden keine Daten verschickt.

Stand: Stufe 1 von 3. Die Vorschläge kommen aus der Größenregel B0. Die strömungsbewusste Empfehlung (Basisrechnung + M1_flow) folgt in Stufe 3.

## Starten

- **Windows:** `windows/4_Defeaturing_Tool.bat` doppelklicken (Voraussetzung: `2_Einrichten.bat` lief einmal). Der Browser öffnet `http://localhost:8765`.
- **Linux/WSL:** `python -m app.server --open`

## Ablauf in der Oberfläche

1. **STL laden** und die Einheit der Datei angeben (STL kennt keine Einheiten).
2. **Features finden** mit zwei Radien:
   - r_max (Vertiefungen): Bohrungen, Nuten, Gravuren, die schmaler als etwa 2·r_max sind, werden gefunden.
   - r_vor (Vorsprünge): Schraubenköpfe, Rippen, erhabene Schrift, die dünner als etwa 2·r_vor sind. **r_vor muss kleiner sein als die halbe Dicke der dünnsten Wand**, sonst wird die Wand selbst zum Feature.
   - Genauigkeit: feineres Voxelgitter für kleine Features (rechnet länger).
3. **Prüfen:** Jedes Feature ist im Bild eingefärbt (grün = entfernen, rot = behalten). Klick im Bild oder auf den Punkt in der Liste schaltet um, Klick auf den Listeneintrag fährt die Kamera hin. Änderungen gegenüber dem Vorschlag sind als „von dir geändert“ markiert.
4. **Exportieren:** ZIP mit `<name>_defeatured.stl` und `<name>_defeaturing.json`. Unter Windows liegt eine Kopie zusätzlich in `%USERPROFILE%\CFD-Ergebnisse\Defeaturing`. „Ergebnis im Bild anzeigen“ zeigt vorher die STL, wie sie exportiert wird.

## Wie es funktioniert (kurz)

| Schritt | Modul | Verfahren |
| --- | --- | --- |
| Hülle | `stl/envelope.py` | Voxelisierung per Strahlparität, morphologisches Schließen (r_max) und Öffnen (r_vor) über euklidische Distanztransformationen |
| Erkennung | `stl/detect.py` | Ein Dreieck gehört zu einem Feature, wenn mindestens 50 % seiner Fläche weiter als ein Voxel von der Hülle abweicht. Zusammenhängende Dreiecke bilden ein Feature. Höhe h = größter Abstand von der Öffnungsebene; Breite b und Länge l aus dem Rand der Öffnung |
| Filter | `stl/detect.py` | Verworfen werden flache Streifen (h ≤ ein Voxel), Bänder um das ganze Bauteil und Kandidaten mit stark gebogenem Rand (Kantenrundung durch Schließen/Öffnen) |
| Vorschlag | `models/baselines.py` | B0: entfernen, wenn h/L < Schwelle (Standard 2 %, L = Diagonale des Bauteils); ±25 % um die Schwelle „unsicher“ (Standard: behalten). Features länger als das halbe Bauteil werden als Bauteilkante eingestuft und behalten |
| Defeaturing | `stl/defeature.py` | Dreiecke des Features ausschneiden, Öffnung mit ebenem Deckel entlang des Originalrands triangulieren (Ringnuten als Polygon mit Loch). Alle anderen Dreiecke bleiben bitgenau erhalten |

Geprüft (pytest) an einer Testplatte mit Durchgangsbohrung, Tasche, Zapfen, Gravur und Rippe: alle fünf werden gefunden, nichts sonst; Höhen auf 5 % genau; das Volumen nach dem Entfernen stimmt mit der Geometrie überein, nach Entfernen aller Features bleibt exakt der Quader 100 × 60 × 10 mm.

## Grenzen von Stufe 1

- **Mindestgröße:** Ein Feature muss etwa 2 bis 3 Voxel tief sein. Bei einem 200-mm-Bauteil sind das in „Standard“ ca. 1,5 mm, in „Fein“ ca. 1 mm.
- **Dünne Bauteilkanten** (z. B. Flügelhinterkante) erkennt das Öffnen als Vorsprung. Sie werden meist verworfen oder als Bauteilkante markiert und behalten. Bitte im Bild prüfen.
- **Features über einer Kante** (z. B. eine Nut, die seitlich aus dem Bauteil läuft) lassen sich nicht mit einem ebenen Deckel schließen. Das Tool lässt sie dann stehen und schreibt den Grund ins Protokoll. Gleiches gilt für Features auf gewölbten Flächen mit unruhigem Rand. Am Testflügel (NACA 0012, 200 mm Sehne) wurden zwei Bohrungen sauber entfernt; eine 1 mm tiefe Gravur wurde erst mit „Fein“ gefunden und dann wegen des unruhigen Rands stehen gelassen. Eine schräg aus der Fläche laufende Gravur wurde gar nicht erkannt. Ein Ergebnis wird nie exportiert, ohne geschlossen zu sein: Bricht ein Deckel die Oberfläche auf, bleibt das Feature stehen.
- **Die Eingabe muss geschlossen sein** (wasserdicht). Kleine Löcher werden repariert, sonst kommt eine Fehlermeldung.
- Der Vorschlag ist nur eine Größenregel und weiß nichts über die Strömung.

## Übergabeformat an das Schwesterprojekt (Entwurf, noch abzustimmen)

**STL:** binär, wasserdicht, eine Oberfläche, Einheit wählbar (Standard m für snappyHexMesh).

**Protokoll `*_defeaturing.json`** (Schema `fad-defeaturing/1`):

| Feld | Inhalt |
| --- | --- |
| `source` | Name, Einheit, SHA-256 und Dreieckszahl der Original-STL |
| `output` | Dateiname, Einheit, Dreiecke, wasserdicht ja/nein, Volumen vorher/nachher |
| `parameters` | r_max, r_vor, Voxelgröße, Schwellen (in der Ausgabeeinheit) |
| `counts` | erkannt, entfernt, behalten, fehlgeschlagen, vom Menschen geändert |
| `features[]` | je Feature: Typ, h, b, l, Fläche, Lage und Normale, Vorschlag mit Begründung, Entscheidung, `decided_by` (`modell`/`mensch`), Status, Abweichung des Deckels |
| `code_revision`, `tool_version`, `created` | Nachvollziehbarkeit |

Offene Fragen an das Schwesterprojekt: Einheit der CadQuery-Exporte (mm oder m)? Eine STL oder mehrere `solid`-Blöcke (Patches)?

## Nächste Stufen

- **Stufe 2 (bis Gate 2, 20.12.):** Selbsttest der Erkennung auf den parametrischen Familien (Precision/Recall), `surfaceCheck` vor dem Export, Option „implizites Defeaturing“ (Verfeinerungsvorschlag statt Geometrieänderung), Format mit dem Schwesterprojekt festzurren.
- **Stufe 3 (11.01.–24.01.):** Basisrechnung an der Hülle (Außenströmung), Empfehlung durch M1_flow mit geschätztem ΔQ.
