# F2-Probelauf in Claudes Sandbox (OpenFOAM v1912, 12.11.2026)

NACA2412, α = 4°, c = 0,1 m, Re = 3·10⁵ (U = 45 m/s, ν = 1,5·10⁻⁵ m²/s), k-ω SST mit Wandauflösung (y₁ aus Plattenreibung für y⁺ ≈ 1), Feature auf der Oberseite bei x/c = 0,5, Breite 0,05c. Feines Netz etwa 105 000 Zellen, 4000 Iterationen. v1912 ohne Function Objects: c_d aus den Endfeldern (`forces_from_fields`), Stabilität aus den Feldern der letzten 750 Iterationen (alle 250 Iterationen geschrieben).

## Ergebnis (Stand e139682 + Nullversuch)

| Fall | c_d | ΔQ_rel | Schwankung letzte 750 It. |
| --- | --- | --- | --- |
| ohne Feature | 0,015169 | 0 | 0,013 % |
| Nut h/c = 0,002 | 0,015516 | +2,28 % | 0,013 % |
| Nut h/c = 0,005 | 0,015895 | +4,78 % | 0,006 % |
| Nut h/c = 0,01 | 0,015881 | +4,69 % | 0,011 % |
| Rippe h/c = 0,002 | 0,015495 | +2,15 % | 0,011 % |
| Rippe h/c = 0,005 | 0,017352 | +14,39 % | 0,004 % |
| Rippe h/c = 0,01 | 0,026716 | +76,12 % | 0,023 % |
| Nullversuch: Fenster neu vernetzt (2 Läufe) | 0,015169 / 0,015166 | 0,000 / −0,024 % | |
| Nullversuch: Außennetz geändert (far 0,4c) | 0,015029 | −0,92 % | 0,20 % |
| grobes Netz (base_coarse) | 0,016102 | +6,15 % | 0,025 % |

c_l ohne Feature: 0,64 (dünne Profiltheorie ≈ 0,67). c_d liegt über typischen Messwerten (≈ 0,010), plausibel, da das Modell die Grenzschicht ab der Vorderkante turbulent rechnet.

## Lesart

- Das numerische Rauschen von ΔQ_rel bei gleichem Außennetz liegt bei etwa 0,02 %, also etwa Faktor 40 unter τ = 1 %.
- Der absolute c_d-Wert ist noch netzabhängig (grob/fein 6 %, Außennetz 0,9 %). Für das Label zählt die Differenz bei gleichem Außennetz, wie bei F1 (GCI von Δp 6,7 %, U(ΔQ) ≈ 0,01 %).
- Nuten: Wirkung steigt bis h/c ≈ 0,005 und bleibt dann gleich. Rippen: stark mit h steigend.
- Laufzeit: etwa 22 min je feinem Fall (ein Kern). Ob 4000 Iterationen nötig sind, zeigt der forceCoeffs-Verlauf auf Tims Rechner.

## Negativbefund (dokumentiert)

Erste Probeläufe mit einem gemeinsam vernetzten Gebiet: Nuten −3,0 / +3,9 / +2,5 %, ohne Ordnung. Ursache: gmsh baut mit Grenzschicht-Feld das ganze Netz bei jeder Geometrieänderung neu auf (73 % der Zellen weiter als 0,2c vom Slot verschoben) und ist selbst bei gleicher Eingabe nicht reproduzierbar. Abhilfe: Außennetz je Basis einmal vernetzen und wiederverwenden, nur das Fenster um den Slot je Fall neu (`cfd/mesh_gmsh.py`).
