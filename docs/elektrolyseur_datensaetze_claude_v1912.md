# Sandbox-Läufe F1, F1x, F2, F2x mit Temperatur (Claude, OpenFOAM v1912, 16.11.2026)

Vergleichswerte aus Claudes Sandbox (ohne Function Objects: dp aus dem Endfeld,
keine iterative Streuung). Tims Laptop (v2606) soll dieselben Klassenanteile
ergeben. Temperatur als passiver Skalar, Pr = 3, Feature-Wand isotherm.

Laufzeit Temperaturschritt: ca. 1,5 s je Fall (Strömung inkl. Netz 5–10 s), also rund +20 %.
Wärmestrom aus der Energiebilanz; Kontrolle über den Wandgradienten weicht um < 0,2 % ab.

Auffällig:
- Gravuren (drei schmale Schlitze) sind in allen Läufen irrelevant, für Druck und Wärme
  (0 von 57). Das Fluid in den Schlitzen steht, die Hauptströmung läuft darüber hinweg.
- Konvexe Formen (Rippe, Fase-Rippe, Noppe, Stufe mit Rampe) sind meist relevant für den Druck.
- Wärme-Relevanz ist seltener als Druck-Relevanz. In F2 gibt es aber Features, die nur für die
  Wärme relevant sind (9 bzw. 7), in F1 keine. Die zwei Labels tragen also unterschiedliche Information.
- Ausschlüsse: checkMesh 5 / 1 / 4 / 4 Fälle; F1 zusätzlich 25 nicht konvergiert (Uy-Plateau ohne Function Objects, siehe AP3).


## Datensatz F1

240 Features aus 30 Basiskonfigurationen, davon 210 gültig und 30 ausgeschlossen.

| Ausschlussgrund | Anzahl |
| --- | --- |
| not converged | 25 |
| checkMesh failed | 5 |

### Klassenbalance (Anteil „relevant“)

| Typ | n | τ = 0,5% | τ = 1,0% | τ = 2,0% |
| --- | --- | --- | --- | --- |
| alle | 210 | 158 (75%) | 114 (54%) | 77 (37%) |
| groove | 106 | 55 (52%) | 22 (21%) | 3 (3%) |
| rib | 104 | 103 (99%) | 92 (88%) | 74 (71%) |

### Klassenbalance Wärmeübergang (Nusselt-Zahl)

210 Features mit gültiger Temperaturrechnung.

| Typ | n | τ = 0,5% | τ = 1,0% | τ = 2,0% |
| --- | --- | --- | --- | --- |
| alle | 210 | 69 (33%) | 25 (12%) | 13 (6%) |
| groove | 106 | 27 (25%) | 1 (1%) | 0 (0%) |
| rib | 104 | 42 (40%) | 24 (23%) | 13 (12%) |

Bei τ = 1 %: 25 Features für beide relevant, 89 nur für den Druck, 0 nur für die Wärme.

### Wertebereiche

| Größe | Min | Median | Max |
| --- | --- | --- | --- |
| Re | 20.7 | 90.7 | 385 |
| h_over_L | 0.0501 | 0.168 | 0.499 |
| w_over_L | 0.101 | 1.07 | 1.99 |
| h_plus | 0.643 | 3.75 | 23.9 |
| h_over_delta | 0.112 | 0.374 | 1.11 |
| dQ_rel | -0.0242 | -0.000171 | 0.532 |
| dNu_rel | -0.0101 | -6.43e-05 | 0.0411 |

### Laufzeit

Fälle mit Feature: Median 2.0 s, Maximum 4.0 s, Summe 8.6 min (seriell).


## Datensatz F1X

150 Features aus 15 Basiskonfigurationen, davon 149 gültig und 1 ausgeschlossen.

| Ausschlussgrund | Anzahl |
| --- | --- |
| checkMesh failed | 1 |

### Klassenbalance (Anteil „relevant“)

| Typ | n | τ = 0,5% | τ = 1,0% | τ = 2,0% |
| --- | --- | --- | --- | --- |
| alle | 149 | 96 (64%) | 69 (46%) | 52 (35%) |
| bump | 30 | 30 (100%) | 18 (60%) | 14 (47%) |
| chamfer_rib | 30 | 28 (93%) | 27 (90%) | 21 (70%) |
| engraving | 29 | 0 (0%) | 0 (0%) | 0 (0%) |
| round_groove | 30 | 11 (37%) | 4 (13%) | 0 (0%) |
| wedge | 30 | 27 (90%) | 20 (67%) | 17 (57%) |

### Klassenbalance Wärmeübergang (Nusselt-Zahl)

149 Features mit gültiger Temperaturrechnung.

| Typ | n | τ = 0,5% | τ = 1,0% | τ = 2,0% |
| --- | --- | --- | --- | --- |
| alle | 149 | 32 (21%) | 15 (10%) | 8 (5%) |
| bump | 30 | 9 (30%) | 6 (20%) | 4 (13%) |
| chamfer_rib | 30 | 10 (33%) | 6 (20%) | 2 (7%) |
| engraving | 29 | 0 (0%) | 0 (0%) | 0 (0%) |
| round_groove | 30 | 6 (20%) | 0 (0%) | 0 (0%) |
| wedge | 30 | 7 (23%) | 3 (10%) | 2 (7%) |

Bei τ = 1 %: 15 Features für beide relevant, 54 nur für den Druck, 0 nur für die Wärme.

### Wertebereiche

| Größe | Min | Median | Max |
| --- | --- | --- | --- |
| Re | 21.2 | 102 | 405 |
| h_over_L | 0.0507 | 0.159 | 0.495 |
| w_over_L | 0.111 | 1.11 | 2 |
| h_plus | 0.635 | 3.66 | 22.2 |
| h_over_delta | 0.113 | 0.353 | 1.1 |
| dQ_rel | -0.0184 | 0.00824 | 0.519 |
| dNu_rel | -0.00951 | 0.000288 | 0.0962 |

### Laufzeit

Fälle mit Feature: Median 3.0 s, Maximum 8.0 s, Summe 7.3 min (seriell).


## Datensatz F2

160 Features aus 20 Basiskonfigurationen, davon 156 gültig und 4 ausgeschlossen.

| Ausschlussgrund | Anzahl |
| --- | --- |
| checkMesh failed | 4 |

### Klassenbalance (Anteil „relevant“)

| Typ | n | τ = 0,5% | τ = 1,0% | τ = 2,0% |
| --- | --- | --- | --- | --- |
| alle | 156 | 56 (36%) | 43 (28%) | 32 (21%) |
| groove | 78 | 7 (9%) | 4 (5%) | 0 (0%) |
| rib | 78 | 49 (63%) | 39 (50%) | 32 (41%) |

### Klassenbalance Wärmeübergang (Nusselt-Zahl)

156 Features mit gültiger Temperaturrechnung.

| Typ | n | τ = 0,5% | τ = 1,0% | τ = 2,0% |
| --- | --- | --- | --- | --- |
| alle | 156 | 61 (39%) | 29 (19%) | 13 (8%) |
| groove | 78 | 19 (24%) | 4 (5%) | 0 (0%) |
| rib | 78 | 42 (54%) | 25 (32%) | 13 (17%) |

Bei τ = 1 %: 20 Features für beide relevant, 23 nur für den Druck, 9 nur für die Wärme.

### Wertebereiche

| Größe | Min | Median | Max |
| --- | --- | --- | --- |
| Re | 22.9 | 97.7 | 460 |
| h_over_L | 0.0503 | 0.161 | 0.499 |
| w_over_L | 0.101 | 1.05 | 1.99 |
| h_plus | 0.0585 | 1.6 | 15.1 |
| h_over_delta | 0.101 | 0.322 | 0.998 |
| dQ_rel | -0.0186 | 0.000266 | 1.31 |
| dNu_rel | -0.0154 | -7.78e-05 | 0.0744 |

### Laufzeit

Fälle mit Feature: Median 4.0 s, Maximum 12.0 s, Summe 12.2 min (seriell).


## Datensatz F2X

150 Features aus 15 Basiskonfigurationen, davon 146 gültig und 4 ausgeschlossen.

| Ausschlussgrund | Anzahl |
| --- | --- |
| checkMesh failed | 4 |

### Klassenbalance (Anteil „relevant“)

| Typ | n | τ = 0,5% | τ = 1,0% | τ = 2,0% |
| --- | --- | --- | --- | --- |
| alle | 146 | 49 (34%) | 37 (25%) | 26 (18%) |
| bump | 30 | 14 (47%) | 13 (43%) | 12 (40%) |
| chamfer_rib | 28 | 15 (54%) | 14 (50%) | 9 (32%) |
| engraving | 28 | 0 (0%) | 0 (0%) | 0 (0%) |
| round_groove | 30 | 4 (13%) | 1 (3%) | 1 (3%) |
| wedge | 30 | 16 (53%) | 9 (30%) | 4 (13%) |

### Klassenbalance Wärmeübergang (Nusselt-Zahl)

146 Features mit gültiger Temperaturrechnung.

| Typ | n | τ = 0,5% | τ = 1,0% | τ = 2,0% |
| --- | --- | --- | --- | --- |
| alle | 146 | 42 (29%) | 27 (18%) | 9 (6%) |
| bump | 30 | 17 (57%) | 12 (40%) | 3 (10%) |
| chamfer_rib | 28 | 13 (46%) | 8 (29%) | 5 (18%) |
| engraving | 28 | 0 (0%) | 0 (0%) | 0 (0%) |
| round_groove | 30 | 7 (23%) | 4 (13%) | 0 (0%) |
| wedge | 30 | 5 (17%) | 3 (10%) | 1 (3%) |

Bei τ = 1 %: 20 Features für beide relevant, 17 nur für den Druck, 7 nur für die Wärme.

### Wertebereiche

| Größe | Min | Median | Max |
| --- | --- | --- | --- |
| Re | 22.2 | 92.8 | 463 |
| h_over_L | 0.0507 | 0.158 | 0.495 |
| w_over_L | 0.111 | 1.16 | 2 |
| h_plus | 0.0796 | 1.52 | 7.46 |
| h_over_delta | 0.101 | 0.316 | 0.99 |
| dQ_rel | -0.0302 | 0.000257 | 0.287 |
| dNu_rel | -0.0145 | 0.000487 | 0.0774 |

### Laufzeit

Fälle mit Feature: Median 4.0 s, Maximum 9.0 s, Summe 10.8 min (seriell).

