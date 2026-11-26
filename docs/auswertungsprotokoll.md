# Auswertungsprotokoll AP6, Teil 1 (B0, B1, M1_geo, M1_flow)

Eingefroren am 26.11.2026, bevor die Modelle zum ersten Mal auf den echten
Datensätzen liefen (HANDOFF 3.9: Testsatz nicht unbewusst mitoptimieren).
Der Git-Commit mit diesem Dokument und `models/evaluate.py` ist der
eingefrorene Stand. Jede spätere Änderung am Verfahren bekommt einen eigenen
Abschnitt „Abweichung“ mit Datum und Grund.

## Daten

- Tims Laptop-Läufe (OpenFOAM v2606): `dataset_f1_alle`, `dataset_f2_alle`,
  `dataset_f3`, `dataset_f4`. Nur gültige Features (`excluded` leer).
- Label Druck: relevant, wenn |ΔQ_rel| > τ. Hauptauswertung τ = 1 %,
  Sensitivität 0,5 % und 2 %.
- Label Wärme: relevant, wenn |ΔNu_rel| > τ, nur Familien mit
  Temperaturrechnung (F1, F2, F4; F3 ist turbulent und ohne Temperatur).
- Grauzone (HANDOFF 3.6): U_ΔQ aus den GCI-Fällen liegt bei etwa 0,01 %,
  also rund hundertmal unter τ. Die Grauzone τ ± U_ΔQ enthält damit höchstens
  einzelne Features. Hauptauswertung ohne Ausschluss, die Anzahl wird berichtet.

## Eingaben (nie die Familie oder der Feature-Typ)

- **D_geo:** konvex/konkav, h/L, w/L, h/w, Flächenanteil, Füllgrad,
  Anzahl Elemente, Orientierung, Re.
- **D_flow:** D_geo plus h⁺, h/δ, c_p, dimensionsloser Druckgradient,
  Kraftanteil, Abstand zur Ablösung, Ablösung ja/nein, Re_h.

## Modelle

- **B0:** relevant, wenn h/L ≥ s₀. **B1:** relevant, wenn h⁺ ≥ s₁.
  s₀ und s₁ auf den Trainingsfamilien gewählt (einziger Parameter).
- **M1_geo, M1_flow:** `HistGradientBoostingClassifier` (scikit-learn),
  Raster max_depth ∈ {2, 3}, learning_rate ∈ {0,05; 0,1}, 300 Bäume,
  mindestens 10 Fälle je Blatt, fester Seed. Auswahl nach Average Precision
  in einer inneren LOFO über die Trainingsfamilien.

## Entscheidungsschwelle (Hauptendpunkt)

Auf den Trainingsfamilien so gewählt, dass dort Recall(relevant) ≥ 0,95.
Für M1 aus den Out-of-fold-Wahrscheinlichkeiten der inneren LOFO, für B0/B1
direkt aus den Trainingsdaten. Auf der Testfamilie berichtet: Recall
(Sicherheit) und Spezifität (Anteil korrekt entfernter irrelevanter Features).

## Testschemata

- **LOFO:** vier Folds, je eine Familie als Test.
- **Innerhalb der Familien:** alle Familien gepoolt, 5 Folds gruppiert nach
  Basiskonfiguration (dieselbe Basis nie in Training und Test), Metriken je
  Familie. Innere Auswahl mit 3 gruppierten Folds.
- **Generalisierungslücke (H2):** Spezifität innerhalb minus LOFO, Mittel
  über die Familien.

## Entscheidungskriterien (aus HANDOFF 2)

- **H1:** M1_flow − B1 ≥ 10 Prozentpunkte Spezifität im Mittel, besser in
  mindestens 3 von 4 Folds, mittlerer Test-Recall nicht schlechter als B1.
- **H2:** Lücke von M1_flow höchstens halb so groß wie die von M1_geo.

## Statistik und Interpretation

- 95 %-Intervall der Spezifitätsdifferenz M1_flow − B1 je Testfamilie aus
  einem Cluster-Bootstrap über Basiskonfigurationen (2000 Ziehungen).
- Gruppierte Permutation Importance (Geometrie gegen Strömung) auf der
  Testfamilie, Maß: Abfall der Average Precision, 20 Wiederholungen.
- Regression ergänzend: MAE von ΔQ_rel mit `HistGradientBoostingRegressor`
  (max_depth 3, learning_rate 0,05).

## Nicht in diesem Teil

L0/L1 (LLM, läuft lokal mit Ollama auf Tims Laptop), F5 und R1–R3 folgen.

## Aufruf

    python -m models.evaluate --data <Ordner mit dataset_*.parquet> --out results/ap6

## Abweichung 1 (26.11.2026, explorativ)

Grund: H2 wurde im eingefrorenen Lauf widerlegt, vermutete Ursache sind absolute
Regimegrößen (Re, Re_h, h⁺) mit familienweise verschiedenen Wertebereichen.
Zusätzliche Eingabesätze ohne Re/Re_h bzw. mit u_τ/U = h⁺ / (h/L · Re) statt h⁺, Re
und Re_h, sonst identisches Verfahren (`models/explore_h2.py`). Die Ergebnisse
werden nur als explorativ berichtet und ersetzen nicht den Test von H2.
