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
| F2: NACA-4-Profil mit Nut/Rippe, turbulent (k-ω SST, y⁺ ≈ 1) | `geometry/families/f2_naca.py`, `cfd/case_f2.py` | Probelauf (`--design f2_trial`) |
| F2-Netz mit gmsh: Außennetz je Basis einmal vernetzt und wiederverwendet, nur ein Fenster am Feature neu (Grenzschicht aus Vierecken, im Fenster dünne Schicht) | `cfd/mesh_gmsh.py` | alle Probefälle bestehen checkMesh; Außennetz knotengleich |

Unter Windows: `windows/5_F1_Datensatz_rechnen.bat` (ruft `scripts/run_design.sh f1` auf).

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
- **F2 mit gmsh statt snappyHexMesh:** snappy verfeinert isotrop, die Wandauflösung für y⁺ ≈ 1 würde im 2D-Slab auch in z gelten. gmsh vernetzt die Ebene direkt mit Viereck-Grenzschicht und extrudiert eine Zelle.
- **F2-Außennetz je Basis wiederverwendet:** Das Grenzschicht-Feld von gmsh liefert bei jeder Änderung (und selbst bei gleicher Eingabe) ein anderes Netz. Das ergab in den ersten Probeläufen ein Rauschen von einigen Prozent in c_d. Jetzt wird nur ein Fenster um den Slot je Fall neu vernetzt; der Rest ist knotengleich.
- **F1-Klassenbalance:** Rippen sind meist relevant, Nuten selten. Die Bereiche bleiben, Metriken werden zusätzlich je Typ berichtet (Entscheidung Tim, 12.11.2026).

## Struktur

```
geometry/    features.py, families/f1_channel.py, families/f2_naca.py
cfd/         templates/f1_channel/, templates/f2_naca/, run_case.py, case_f2.py, mesh_gmsh.py,
             postprocess.py, foamio.py
descriptors/ geometric.py, flow.py
pipeline/    sweep.py (Design + Batch), build_dataset.py, ap2_report.py (Gate 1),
             dataset_report.py
tests/       pytest, ohne OpenFOAM
docs/        Vergleichswerte
env/         environment.yml, requirements.txt
data/        raw/, processed/ (nicht in git)
```

Noch nicht enthalten: voller F2-Versuchsplan, F3–F5, Modelle und Evaluation (AP6).
