# Sandbox-Lauf F3 Einlass-Port (Claude, OpenFOAM v1912, 25.11.2026)

Vergleichswerte ohne Function Objects (Konvergenz nur über Residuen). Probelauf (Re 10⁴, S = H):
Nulltest 0,003 % in Δp₀; Rippen im Rezirkulationsgebiet senken Δp₀ (−1,1/−4,3/−10,3 % für
h/H 0,1/0,25/0,5). Wiederanlegen etwa 8 S hinter der Stufe.

Negative Ergebnisse auf dem Weg dorthin:
- Statischer Druckverlust als Zielgröße: hinter der Erweiterung steigt der Druck, Δp ist negativ
  und kann nahe null liegen. Abhilfe: Totaldruckverlust Δp₀.
- Scharfe Stufenkante: schiefe Flächen an der konvexen Ecke, checkMesh-Fehler in 154 von 248
  Fällen. Abhilfe: Kantenradius 0,05 H.
- Danach noch 52 von 248 Fällen mit ein bis zwei leicht schiefen Wandflächen (Schiefe 4–11) am
  Fuß des Features. Das hängt chaotisch von der genauen Lage ab: dasselbe Feature besteht in F1
  und bei halbem H. Abhilfe: Feature um H/400 verschieben und neu vernetzen (höchstens dreimal).
  49 von 52 Fällen danach in Ordnung (33 beim ersten, 12 beim zweiten, 4 beim dritten Versuch).
- Drei Basen (b011, b016, b019) bleiben im Residuum über der Grenze (p ≈ 2–6·10⁻⁵, Uy bis 5·10⁻⁴;
  b016 knapp, Uy 3·10⁻⁶). Ohne Function Objects lässt sich in der Sandbox nicht prüfen, ob Δp₀
  trotzdem stabil ist. Auf Tims Rechner entscheidet das zusätzlich das Stabilitätskriterium der
  Zielgröße; dort können diese Basen gültig werden.

## Datensatz F3

200 Features aus 20 Basiskonfigurationen, davon 146 gültig und 54 ausgeschlossen.

| Ausschlussgrund | Anzahl |
| --- | --- |
| not converged | 52 |
| checkMesh failed | 2 |

### Klassenbalance (Anteil „relevant“)

| Typ | n | τ = 0,5% | τ = 1,0% | τ = 2,0% |
| --- | --- | --- | --- | --- |
| alle | 146 | 46 (32%) | 31 (21%) | 20 (14%) |
| bump | 13 | 5 (38%) | 5 (38%) | 5 (38%) |
| chamfer_rib | 15 | 8 (53%) | 6 (40%) | 2 (13%) |
| engraving | 15 | 0 (0%) | 0 (0%) | 0 (0%) |
| groove | 29 | 5 (17%) | 2 (7%) | 1 (3%) |
| rib | 30 | 16 (53%) | 13 (43%) | 9 (30%) |
| round_groove | 15 | 2 (13%) | 1 (7%) | 0 (0%) |
| wedge | 29 | 10 (34%) | 4 (14%) | 3 (10%) |

### Wertebereiche

| Größe | Min | Median | Max |
| --- | --- | --- | --- |
| Re | 5.83e+03 | 1.18e+04 | 2.74e+04 |
| h_over_L | 0.0507 | 0.152 | 0.495 |
| w_over_L | 0.113 | 1.09 | 2 |
| h_plus | 3.29 | 25.1 | 162 |
| h_over_delta | 0.101 | 0.304 | 0.99 |
| dQ_rel | -0.105 | -0.000398 | 0.0771 |

### Laufzeit

Fälle mit Feature: Median 47.0 s, Maximum 110.0 s, Summe 111.2 min (seriell).
