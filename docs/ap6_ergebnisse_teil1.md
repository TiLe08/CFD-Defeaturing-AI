# Ergebnisse AP6, Teil 1 (Claude, 26.11.2026)

Erster Lauf nach dem eingefrorenen Protokoll (`docs/auswertungsprotokoll.md`,
Commit 6930b22) auf Tims Laptop-Datensätzen F1–F4 (1081 gültige Features).
Alle Tabellen: `python -m models.evaluate --data <datensaetze> --out results/ap6`.

## Kurzfassung (Stichpunkte für den Bericht)

- **H1 bestätigt** (Druck, τ = 1 %): M1_flow entfernt im Mittel 53 % der irrelevanten
  Features, B1 27 %, B0 25 %. Besser in 4 von 4 Testfamilien, Recall 97 % gegen 96 %.
  Auch bei τ = 2 % erfüllt. Bei τ = 0,5 % ist die Spezifität höher (70 % gegen 17 %),
  aber der Recall von M1_flow liegt knapp unter B1 (92 % gegen 94 %), das Kriterium ist
  dort formal nicht erfüllt.
- **H2 widerlegt:** Strömungsgrößen helfen innerhalb der bekannten Familien stark
  (M1_flow 75–90 % Spezifität), übertragen sich aber schlechter auf eine unbekannte
  Familie. Lücke M1_flow +30 pp, M1_geo +7 pp. Vermutete Ursache: die Strömungsgrößen
  haben je Familie eigene Wertebereiche (laminar Re ≤ 500 gegen F3 turbulent Re ~10⁴,
  h⁺ 0,5–10 in F4 gegen bis 230 in F3). Das Modell extrapoliert dort.
- **Achtung beim Vergleich M1_geo gegen M1_flow:** M1_geo hat im LOFO die höhere
  Spezifität (61 %), verfehlt aber auf F3 und F4 die Sicherheitsvorgabe (Recall 86 % bzw.
  84 % statt ≥ 95 %). M1_flow hält den Recall (92–100 %).
- **Regression extrapoliert schlecht:** MAE von ΔQ_rel für M1_flow auf F3 = 0,35
  (Werte von ΔQ_rel liegen dort zwischen −0,1 und +0,2). Klassifikation ist robuster als
  Regression.
- **Wärme (Nusselt, nur F1, F2, F4):** Die Größenregel B0 ist hier am besten (69 %
  Spezifität), M1 bleibt sehr vorsichtig (Recall 100 %, Spezifität 30–40 %). Mit nur zwei
  Trainingsfamilien je Fold reicht die Datenbasis für ein gelerntes Modell nicht.
- Grauzone τ ± U_ΔQ: 3 Features, wie im Protokoll erwartet vernachlässigbar.
- Engravings sind in keinem Datensatz relevant. Sie stützen die Spezifität aller Modelle.

## Mögliche nächste Schritte (nicht Teil des eingefrorenen Verfahrens)

- Für H2 als dokumentierte Abweichung testen: Strömungsgrößen relativ zur eigenen Basis
  normieren (z. B. h⁺ / h⁺_Basis-Mittel) oder log-transformieren. Getrennt als
  „explorativ“ berichten.
- F5 (3D) bringt eine fünfte Familie und entschärft die Extrapolation.
- L0/L1 (LLM) auf Tims Laptop.

## Auswertung Druckverlust, τ = 1,0%

Verfahren nach docs/auswertungsprotokoll.md. Schwelle auf den Trainingsfamilien für Recall ≥ 0,95.

| Familie | n | relevant |
| --- | --- | --- |
| F1 | 384 | 195 (51%) |
| F2 | 302 | 81 (27%) |
| F3 | 198 | 51 (26%) |
| F4 | 197 | 92 (47%) |

### LOFO: Spezifität (Recall) je Testfamilie

| Testfamilie | B0 | B1 | M1_geo | M1_flow |
| --- | --- | --- | --- | --- |
| F1 | 29 % (92 %) | 13 % (95 %) | 46 % (100 %) | 35 % (100 %) |
| F2 | 21 % (91 %) | 55 % (91 %) | 57 % (96 %) | 61 % (96 %) |
| F3 | 21 % (100 %) | 0 % (100 %) | 69 % (86 %) | 47 % (92 %) |
| F4 | 27 % (98 %) | 39 % (97 %) | 74 % (84 %) | 70 % (98 %) |
| Mittel | 25 % (95 %) | 27 % (96 %) | 61 % (92 %) | 53 % (97 %) |

### Innerhalb der Familien (gruppiert nach Basis) und Generalisierungslücke

| Familie | B0 | B1 | M1_geo | M1_flow |
| --- | --- | --- | --- | --- |
| F1 | 27 % (93 %) | 13 % (95 %) | 78 % (100 %) | 88 % (99 %) |
| F2 | 21 % (93 %) | 54 % (93 %) | 64 % (90 %) | 90 % (88 %) |
| F3 | 22 % (100 %) | 0 % (100 %) | 65 % (90 %) | 80 % (86 %) |
| F4 | 28 % (97 %) | 40 % (97 %) | 68 % (95 %) | 75 % (97 %) |
| Lücke (Mittel) | +0 pp | -0 pp | +7 pp | +30 pp |

### Hypothesen

- H1: M1_flow − B1 = +26.4 pp Spezifität im Mittel, besser in 4 von 4 Folds, Recall nicht schlechter: ja. Kriterium erfüllt: ja.
- H2: Lücke M1_flow +30 pp, M1_geo +7 pp. Kriterium (flow ≤ halbe geo-Lücke) erfüllt: nein.

### Bootstrap und Permutation Importance (M1_flow, Testfamilie)

| Testfamilie | 95 %-KI Spezifität M1_flow − B1 | Abfall AP Geometrie | Abfall AP Strömung |
| --- | --- | --- | --- |
| F1 | +16 bis +28 pp | 0.296 | 0.082 |
| F2 | -5 bis +17 pp | 0.416 | 0.384 |
| F3 | +43 bis +51 pp | 0.375 | 0.255 |
| F4 | +20 bis +43 pp | 0.268 | 0.190 |

### Regression (MAE von ΔQ_rel, LOFO)

| Testfamilie | M1_geo | M1_flow |
| --- | --- | --- |
| F1 | 0.0428 | 0.0877 |
| F2 | 0.0389 | 0.0292 |
| F3 | 0.0651 | 0.3544 |
| F4 | 0.0171 | 0.0344 |
