# CFD-Defeaturing-AI

Research project for uni. Goal is to build an AI to do flow-aware defeaturing on STL files to make CFD simulations better.

**Unter Windows ohne Vorkenntnisse:** siehe [ANLEITUNG_WINDOWS.md](ANLEITUNG_WINDOWS.md). Doppelklick-Skripte im Ordner `windows/` erledigen Installation, den AP2-Lauf und starten das Defeaturing-Tool.

**Defeaturing-Tool (Stufe 1):** STL laden, erkannte Features im Browser prüfen und per Klick behalten oder entfernen, bereinigte STL plus Protokoll exportieren. Start mit `python -m app.server --open` oder `windows/4_Defeaturing_Tool.bat`. Details und Grenzen: [docs/defeaturing_tool.md](docs/defeaturing_tool.md).

## Stand AP2 (Entwurf)

Code für das Research Project „Flow-Aware Defeaturing“ (TH Ulm, WiSe 2026/27). Grundlage sind der Plan in `HANDOFF_Flow-Aware-Defeaturing.md` und das Konzept „Technische Umsetzung“. Dieser Stand deckt AP2 ab, also den Machbarkeitsnachweis für Gate 1 an der Familie F1 (Kanal mit Wandfeature, laminar).

Die Implementierung entstand unter Verwendung des KI-Assistenten Claude (Anthropic) als Programmierwerkzeug. Konzeption, Validierung und Interpretation liegen beim Autor.

## Was schon funktioniert

| Schritt | Modul | Getestet |
| --- | --- | --- |
| Geometrie F1 (Nut/Rippe), STL mit Patches | `geometry/families/f1_channel.py` | pytest; Netz mit OpenFOAM erzeugt |
| Case bauen, vernetzen, rechnen, auswerten (wiederaufnahmefähig) | `cfd/run_case.py`, `cfd/postprocess.py`, `cfd/foamio.py` | OpenFOAM v1912 in Claudes Umgebung, siehe unten |
| AP2-Design (14 Fälle) und paralleler Batch | `pipeline/sweep.py` | komplett durchgerechnet |
| Deskriptoren D_geo und D_flow | `descriptors/` | pytest, inkl. Skaleninvarianz bei gleichem Re |
| Datensatz (eine Zeile je Feature, Ausschlüsse mit Grund) | `pipeline/build_dataset.py` | auf den AP2-Ergebnissen |
| Gate-1-Auswertung (Nullversuche, GCI, Laufzeit) | `pipeline/ap2_report.py` | auf den AP2-Ergebnissen |
| STL: Hülle, Feature-Erkennung, Defeaturing (AP5, vorgezogen) | `stl/` | pytest an Testplatte mit 5 bekannten Features |
| Größenregel B0 | `models/baselines.py` | pytest |
| Defeaturing-Tool mit Browser-Oberfläche | `app/` | pytest (API) und automatischer Browsertest |

Die Ergebnisse von Claudes Testlauf liegen in `docs/ap2_testlauf_claude_v1912.md` als Vergleichswerte.

## Stand AP3 (Entwurf)

| Baustein | Datei | Stand |
| --- | --- | --- |
| F1-Versuchsplan (30 Basen × 8 Features, LHS, Re 20–500, h/H 0,05–0,5, w/H 0,1–2) | `pipeline/sweep.py` (`--design f1`) | in Claudes Sandbox durchgerechnet |
| Datensatz-Bericht (Ausschlüsse, Klassenbalance, Wertebereiche) | `pipeline/dataset_report.py` | auf F1 |
| A1 (Anwendungsbeispiel, bis 16.11. F2): NACA-4-Profil mit Nut/Rippe, turbulent (k-ω SST, y⁺ ≈ 1) | `geometry/families/a1_naca.py`, `cfd/case_a1.py` | Probelauf (`--design a1_trial`) |
| A1-Netz mit gmsh: Außennetz je Basis einmal vernetzt und wiederverwendet, nur ein Fenster am Feature neu (Grenzschicht aus Vierecken, im Fenster dünne Schicht) | `cfd/mesh_gmsh.py` | alle Probefälle bestehen checkMesh; Außennetz knotengleich |

| F2 Verteiler (Manifold) mit vier Abzweigen, Feature am Boden unter einem Abzweig (Re 20–500, b/H 0,3–1, Teilung 1,5–3 H) | `geometry/families/f2_manifold.py`, `--design f2` (20 Basen × 8 Features) | Probelauf und Sandbox-Lauf |
| F3 Einlass-Port: Zulaufkanal mit Stufe in die Kammer (rückwärtige Stufe), turbulent mit k-ω SST und Wandfunktionen (Spalding), Stufenkante mit Radius 0,05 H, Feature am Kammerboden 1–12 Stufenhöhen hinter der Stufe; Zielgröße Totaldruckverlust; Re 5·10³–3·10⁴, S/H 0,5–2, alle sieben Feature-Typen, keine Temperatur | `geometry/families/f3_port.py`, `cfd/templates/f3_port/`, `--design f3` (20 Basen × 10 Features) | Probelauf und Sandbox-Lauf |
| F4 Pin-Flowfield: zwei versetzte Reihen quadratischer Pins (Ecken r = 0,1 H) zwischen Seitenwänden, Feature an der Seitenwand unter einem Pin (Re 10–60, a/H 0,5–1, Teilung 1,5–3 H, alle sieben Feature-Typen) | `geometry/families/f4_pins.py`, `--design f4` (20 Basen × 10 Features) | Probelauf und Sandbox-Lauf |
| F5 Bipolarplatten-Kanal in 3D: Rechteckkanal (Breite W/H 1–3), ein Feature am Boden in Kanalmitte (Loch, Pin, Nut-Stück, Rippen-Stück mit Spannweite b), laminar, Re 20–200, h/H 0,1–0,5, keine Temperatur | `geometry/families/f5_duct.py`, `cfd/templates/f5_duct/`, `--design f5` (8 Basen × 6 Features) | Probelauf |
| Wärmeübergang: Temperatur als passiver Skalar auf dem fertigen Strömungsfeld (`scalarTransportFoam`), Feature-Wand isotherm, andere Wände adiabat, Pr = 3 (Wasser, 60–80 °C); Zielgröße Nusselt-Zahl, eigenes Label `relevant_th_tau*` | `cfd/templates/f1_channel/thermal/`, `cfd/postprocess.py` | F1 und F2; ca. +20 % Rechenzeit |
| STL-Paket der Elektrolyseur-Modelle (Platte und Fluidraum, mm) | `pipeline/export_models.py` | F1 und F2 |

Unter Windows: `windows/5_F1_Datensatz_rechnen.bat`, `6_F2_...` und `7_F4_...`, `8_F3_...` und `10_F5_...` (rufen `scripts/run_design.sh f1_alle`, `f2_alle`, `f4`, `f3` bzw. `f5` auf), `9_LLM_auswerten.bat` ruft `scripts/run_llm.sh` auf (L0/L1 mit Ollama). Fälle, die vor der Temperaturrechnung gerechnet wurden, bekommen beim nächsten Start nur den Temperaturschritt nachgerechnet.

## Einrichtung (WSL2/Ubuntu)

```bash
# Python-Umgebung (eine der beiden Varianten)
conda env create -f env/environment.yml && conda activate fad
# oder
python3.11 -m venv .venv && . .venv/bin/activate && pip install -r env/requirements.txt

# Tests (ohne OpenFOAM, < 5 s)
python -m pytest -q

# OpenFOAM-Umgebung bekannt machen (Pfad an deine ESI-Version anpassen)
export FOAM_BASHRC=/usr/lib/openfoam/openfoam2406/etc/bashrc
```

## AP2 rechnen

```bash
# 1. Plan ansehen (legt data/raw/<case_id>/spec.json an, rechnet nichts)
python -m pipeline.sweep --design ap2 --plan-only

# 2. Ein einzelner Fall als Rauchtest
python -m cfd.run_case data/raw/f1_ap2_b000_without

# 3. Alle 14 Fälle; --workers = physische Kerne minus 1
python -m pipeline.sweep --design ap2 --workers <N>

# 4. Gate-1-Auswertung (schreibt data/raw/ap2_summary.md)
python -m pipeline.ap2_report --workers <N> --planned-runs 900
```

Abbrechen ist jederzeit möglich. Ein erneuter Aufruf überspringt fertige Fälle. Fehlgeschlagene Fälle werden nur mit `python -m cfd.run_case <case> --retry-failed` erneut versucht. `--clean` setzt einen Fall auf seine `spec.json` zurück.

Jeder Fall enthält `status.json` (Zustand, erledigte Schritte, Zeiten), `result.json` (Δp, Streuung, Zellen, Laufzeit, Konvergenz), `wall_*.csv` (Wanddaten), `profile_slot.csv` (Geschwindigkeitsprofil über dem Feature-Slot) und `case.foam` für ParaView.

## Was du beim ersten Lauf bitte prüfst

Claudes Umgebung hat nur OpenFOAM v1912 aus dem Ubuntu-Paket. Dort brechen alle Function Objects mit einem Fehler im Paket ab (`IOstream "sha1"`). Der Testlauf lief deshalb mit `--no-function-objects`: Δp kommt dann aus dem Endfeld (ohne Iterationsstreuung), τ_w aus einer laminaren Näherung. Mit deiner ESI-Version sollten die Function Objects laufen. Bitte nach dem Rauchtest prüfen:

1. In `result.json` steht `"dp_source": "function_object"` und `"tau_source": "function_object"`.
2. `dp` weicht weniger als etwa 1 % vom Wert in `docs/ap2_testlauf_claude_v1912.md` ab (Netz und Löser sind identisch, nur die Version unterscheidet sich).
3. In ParaView: Rezirkulation in der Nut, Strömung um die Rippe, keine verzerrten Zellen an den Ecken.
4. Falls `extrudeMesh` ein Netz mit negativen Volumen erzeugt (`checkMesh` meldet Fehler): in `pipeline/sweep.py` `flip_normals` auf `False` setzen. In v1912 war `True` korrekt.

## Erste Befunde aus Claudes Testlauf (vorläufig, v1912)

- Die Pipeline läuft durch: 14 von 14 Fällen gelöst, `checkMesh` überall OK, 2D-F1-Fälle mit rund 8.700 Zellen brauchen etwa 2–3 s.
- **Netzkonsistenz bestätigt:** Ohne Verfeinerungsbox weicht Δp um −0,38 % ab, mit um eine halbe Zelle verschobener Box nur um −0,009 %. Ohne die gemeinsame Box wäre der Netzfehler größer als der Effekt der Nuten.
- **GCI:** Δp selbst hat einen GCI von 6,7 %, ΔQ_rel aber nur eine Unsicherheit von etwa ±0,008 %, weil sich der Diskretisierungsfehler in der Differenz fast aufhebt. Genau deshalb wird der GCI von ΔQ und nicht von Q bewertet.
- **Effekte:** Nuten senken Δp bei Re = 100 nur um 0,12–0,14 % (unter τ = 1 %), Rippen erhöhen es um 0,45 / 1,29 / 4,41 % für h/H = 0,05 / 0,1 / 0,2. Für den Datensatz heißt das: Bei laminarer Kanalströmung sind Nuten fast nie relevant, Rippen schon ab h/H ≈ 0,1.
- Ein Fall (Rippe h/H = 0,1) erreichte das Residuenkriterium für U nicht (Uy stagniert bei 5·10⁻⁶ nach ~200 Iterationen). Mit Function Objects greift dann das Stabilitätskriterium für Δp. Falls das häufiger vorkommt: `res_u` in `pipeline/sweep.py` auf 1e-6 lockern.

## Bewusste Entscheidungen (für das Entscheidungslog)

- **F1 ohne CadQuery:** Die 2D-Kontur entsteht mit shapely und wird mit trimesh extrudiert. Für ein 2D-Polygon ist das exakt und spart die OpenCascade-Abhängigkeit. CadQuery bleibt für F5 (3D) vorgesehen.
- **Wanddaten aus den Feldern statt aus Sampling-Function-Objects:** Das Ausgabeformat der Sampling-Function-Objects hat sich zwischen ESI-Versionen geändert. Die Feld- und Netzdateien sind stabil, `cfd/foamio.py` liest sie direkt.
- **Verfeinerungsbox aus der maximalen Slot-Größe:** Die Box hängt nur von der Basiskonfiguration ab. Damit teilt sich ein Lauf „ohne Feature“ mit allen K Features derselben Basis, statt je Feature einen eigenen Referenzlauf zu brauchen.
- **Grobe Basisrechnung je Basis** (`base_coarse`) als Quelle der Strömungsdeskriptoren, wie im Konzept beschrieben.
- **NACA-Profil (A1) mit gmsh statt snappyHexMesh:** snappy verfeinert isotrop, die Wandauflösung für y⁺ ≈ 1 würde im 2D-Slab auch in z gelten. gmsh vernetzt die Ebene direkt mit Viereck-Grenzschicht und extrudiert eine Zelle.
- **A1-Außennetz je Basis wiederverwendet:** Das Grenzschicht-Feld von gmsh liefert bei jeder Änderung (und selbst bei gleicher Eingabe) ein anderes Netz. Das ergab in den ersten Probeläufen ein Rauschen von einigen Prozent in c_d. Jetzt wird nur ein Fenster um den Slot je Fall neu vernetzt; der Rest ist knotengleich.
- **NACA-Profil von F2 zu A1 (16.11.2026):** Fokus auf Elektrolyseur-Bauteile (Entscheidung Tim). F2 ist jetzt der Verteiler; das Profil bleibt als Anwendungsbeispiel für das Schlusskapitel.
- **Wärmeübergang ohne Kopplung:** einphasig, konstante Stoffwerte, keine Elektrochemie, keine Wärmeleitung in der Platte. Die Temperatur beeinflusst die Strömung nicht, deshalb reicht eine lineare Gleichung auf dem eingefrorenen Feld. Wärmestrom aus der Energiebilanz (Auslass plus Rückdiffusion am Einlass), exakt für die diskrete Lösung; die Schätzung aus dem Wandgradienten weicht um < 0,1 % ab. Zwei getrennte Labels für Druck und Wärme (Entscheidung Tim, 16.11.2026).
- **F4 mit gerundeten Pin-Ecken (r = 0,1 H) und L in ganzen H:** Mit scharfen Ecken erzeugte snappyHexMesh an den konvexen Pin-Ecken einzelne stark schiefe Zellen (checkMesh-Fehler in 11 von 12 Probefällen). Gefräste Pins haben ohnehin einen Eckenradius. Ein beliebiges L (aus Teilung und Pingröße) gab schiefe Flächen an der Auslass-Ecke; L wird deshalb auf ganze H aufgerundet. Re ≤ 60, damit die Strömung hinter den Pins stationär bleibt: Im ersten Sandbox-Lauf mit Re bis 150 blieb das Residuum aller Basen über Re ≈ 75 mit großen Pins bei 1e-2 stehen (instationärer Nachlauf).
- **F3 Zielgröße Totaldruckverlust:** Hinter einer Erweiterung steigt der statische Druck. Δp statisch ist negativ und kann nahe null liegen, dann wird dQ_rel unbrauchbar. Daher gilt Δp₀ = Δp + ½U²(1 − (H/(H+S))²) mit Bulk-Geschwindigkeiten.
- **F3 Stufenkante gerundet (r = 0,05 H):** Mit scharfer Kante erzeugte snappyHexMesh an der konvexen Ecke schiefe Flächen (checkMesh-Fehler in 154 von 200 Features des ersten Sandbox-Laufs, je nach Stufenhöhe). Der Radius ist klein gegen die Stufenhöhe (≥ 0,5 H), die Ablösung bleibt an der Kante.
- **Netz-Wiederholung mit verschobenem Feature:** Scheitert checkMesh bei einem Fall mit Feature (meist ein bis zwei leicht schiefe Wandflächen am Fuß des Features, Schiefe 4–11), wird das Feature um H/400 (1 % einer feinen Zelle) verschoben und neu vernetzt, höchstens dreimal (+1, −1, +2 Schritte). Die Fläche hängt chaotisch von der genauen Lage ab: dasselbe Feature besteht in F1 oder bei halbem H. Die verschobene Lage steht in `spec.json` (`mesh_retry`), Labels und Deskriptoren gehören also zur gerechneten Geometrie; `mesh_retry` ist eine Spalte im Datensatz.
- **F3 ohne Temperatur:** `scalarTransportFoam` kennt keine turbulente Diffusivität. Ein turbulentes Wärmeübergangsmodell (Pr_t, thermische Wandfunktion) wäre ein eigener Validierungsschritt. Es wird als Grenze im Bericht genannt.
- **F5 mit einer Verfeinerungsstufe weniger im Feature-Kasten:** Ein Kasten der Stufe 2 über die ganze Kanalbreite ergäbe etwa 300 000 Zellen je Fall. Mit Stufe 1 sind es etwa 177 000 Zellen und rund 2 Minuten je Fall; deshalb h ≥ 0,1 H (zwei Zellen). Die Linien-Deskriptoren werden auf einem Bodenstreifen um die Kanalmitte ausgewertet, der Kraftanteil über die Grundfläche des Features.
- **F1-Klassenbalance:** Rippen sind meist relevant, Nuten selten. Die Bereiche bleiben, Metriken werden zusätzlich je Typ berichtet (Entscheidung Tim, 12.11.2026).

## Struktur

```
geometry/    features.py, families/f1_channel.py, families/f2_manifold.py, families/f3_port.py, families/f4_pins.py, families/f5_duct.py, families/a1_naca.py
cfd/         templates/f1_channel/, templates/f3_port/, templates/f5_duct/, templates/a1_naca/, run_case.py, case_a1.py, mesh_gmsh.py,
             postprocess.py, foamio.py
descriptors/ geometric.py, flow.py
pipeline/    sweep.py (Design + Batch), build_dataset.py, ap2_report.py (Gate 1),
             dataset_report.py
tests/       pytest, ohne OpenFOAM
docs/        Vergleichswerte
env/         environment.yml, requirements.txt
data/        raw/, processed/ (nicht in git)
```

Noch nicht enthalten: Realfälle (R1–R3).
