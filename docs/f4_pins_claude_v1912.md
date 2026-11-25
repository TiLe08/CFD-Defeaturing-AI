# Sandbox-Lauf F4 Pin-Flowfield (Claude, OpenFOAM v1912, 24.11.2026)

Vergleichswerte ohne Function Objects. Probelauf (Re 50, Standard-Pinfeld): Nulltest
(verschobene Verfeinerungsbox) −0,014 % in Δp und −0,004 % in Nu; Rippe h/H 0,1/0,25/0,5:
Δp +1,4/+6,2/+24 %, Nu −0,4/−1,7/−8,0 % (die Rippe lenkt Fluid von der beheizten Wand weg).

Negative Ergebnisse auf dem Weg dorthin:
- Scharfe Pin-Ecken: einzelne stark schiefe Zellen an den konvexen Ecken (checkMesh in 11 von 12
  Probefällen). Abhilfe: Eckenradius 0,1 H.
- Beliebige Kanallänge: schiefe Flächen an der Ecke Auslass/Wand. Abhilfe: L auf ganze H aufrunden.
- Re bis 150: alle Basen über Re ≈ 75 mit großen Pins instationär (Residuum bleibt bei 1e-2),
  61 von 200 Features ausgeschlossen. Abhilfe: Re 10–60.

## Datensatz F4

200 Features aus 20 Basiskonfigurationen, davon 193 gültig und 7 ausgeschlossen.

| Ausschlussgrund | Anzahl |
| --- | --- |
| not converged | 4 |
| checkMesh failed | 3 |

### Klassenbalance (Anteil „relevant“)

| Typ | n | τ = 0,5% | τ = 1,0% | τ = 2,0% |
| --- | --- | --- | --- | --- |
| alle | 193 | 130 (67%) | 90 (47%) | 54 (28%) |
| bump | 19 | 15 (79%) | 10 (53%) | 6 (32%) |
| chamfer_rib | 20 | 19 (95%) | 15 (75%) | 10 (50%) |
| engraving | 17 | 0 (0%) | 0 (0%) | 0 (0%) |
| groove | 40 | 22 (55%) | 13 (32%) | 1 (2%) |
| rib | 38 | 36 (95%) | 27 (71%) | 20 (53%) |
| round_groove | 19 | 8 (42%) | 4 (21%) | 0 (0%) |
| wedge | 40 | 30 (75%) | 21 (52%) | 17 (42%) |

### Klassenbalance Wärmeübergang (Nusselt-Zahl)

193 Features mit gültiger Temperaturrechnung.

| Typ | n | τ = 0,5% | τ = 1,0% | τ = 2,0% |
| --- | --- | --- | --- | --- |
| alle | 193 | 62 (32%) | 45 (23%) | 21 (11%) |
| bump | 19 | 7 (37%) | 6 (32%) | 2 (11%) |
| chamfer_rib | 20 | 12 (60%) | 8 (40%) | 5 (25%) |
| engraving | 17 | 0 (0%) | 0 (0%) | 0 (0%) |
| groove | 40 | 2 (5%) | 1 (2%) | 0 (0%) |
| rib | 38 | 21 (55%) | 17 (45%) | 9 (24%) |
| round_groove | 19 | 1 (5%) | 0 (0%) | 0 (0%) |
| wedge | 40 | 19 (48%) | 13 (32%) | 5 (12%) |

Bei τ = 1 %: 45 Features für beide relevant, 45 nur für den Druck, 0 nur für die Wärme.

### Wertebereiche

| Größe | Min | Median | Max |
| --- | --- | --- | --- |
| Re | 10.6 | 22.8 | 56.3 |
| h_over_L | 0.0501 | 0.157 | 0.495 |
| w_over_L | 0.111 | 1.11 | 2 |
| h_plus | 0.464 | 2.25 | 9.98 |
| h_over_delta | 0.1 | 0.33 | 1.43 |
| dQ_rel | -0.0253 | 0.00597 | 0.157 |
| dNu_rel | -0.0543 | -0.00256 | 0.0112 |

### Laufzeit

Fälle mit Feature: Median 8.0 s, Maximum 14.0 s, Summe 27.6 min (seriell).

