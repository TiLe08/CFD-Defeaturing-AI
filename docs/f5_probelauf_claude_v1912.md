# F5 Probelauf (Sandbox, OpenFOAM v1912, ohne Function Objects)

Stand 26.11.2026, `python -m pipeline.sweep --design f5_trial`, 4 Worker.

## Aufbau

- Rechteckkanal H = 2 mm, Breite W = 2 H, Länge 20 H (8 H vor, 12 H nach dem Feature), laminar, Re = 100 (mit H).
- Feature am Boden in Kanalmitte, w = 0,8 H in Strömungsrichtung, Spannweite b = 1,0 H bei den Rechteck-Formen.
- Netz: 10 Zellen je H, Wand Stufe 1, Feature-Kasten über die ganze Breite Stufe 1 (2D-Familien: Stufe 2).

## Ergebnisse

| Fall | Zellen | Iterationen | Laufzeit | ΔQ_rel |
| --- | --- | --- | --- | --- |
| ohne Feature | 177 319 | 162 | 86 s | – |
| Nulltest (Kasten um 0,5 Zellen verschoben) | 177 319 | 164 | 87 s | < 1·10⁻⁶ |
| grobe Basis (ohne Verfeinerung) | 40 000 | 169 | 16 s | Δp −3,2 % gegen fein |
| Loch h = 0,1 / 0,3 H | ≈ 178 000 | 160 | 85–89 s | −0,15 % / −0,15 % |
| Pin h = 0,1 / 0,3 H | ≈ 176 000 | 154–160 | 90–95 s | +0,75 % / +4,8 % |
| Nut-Stück h = 0,1 / 0,3 H | ≈ 179 000 | 160 | 87–94 s | −0,25 % / −0,26 % |
| Rippen-Stück h = 0,1 / 0,3 H | ≈ 176 000 | 152–160 | 81–85 s | +1,1 % / +7,5 % |

- checkMesh 11/11 bestanden, alle Fälle konvergiert (Residuen p < 1e-6, U < 1e-7).
- Plausibilität Basisfall: voll entwickelte Strömung im Rechteckkanal (Seitenverhältnis 0,5, f·Re = 62,2 mit D_h) ergibt Δp = 0,0087 m²/s²; mit dem Einlaufverlust (Blockprofil am Einlass) passen die gerechneten 0,0105 m²/s².
- Vertiefungen wirken schwach und kaum mit der Tiefe: Die Strömung tritt bei Re_h ≤ 30 nur wenig in die Kavität ein. Erhebungen wirken stark, wie in F1.
- Alle Deskriptoren werden berechnet. Linien-Größen auf einem Bodenstreifen |z − W/2| < 0,5 d um die Kanalmitte, Kraftanteil über die Grundfläche.

## Behobene Fehler

- `Mesh.n_cells` las die Zellzahl nur aus `owner`. In 3D kann die letzte Zelle innen liegen und keine Fläche besitzen. Jetzt zählt auch `neighbour`.
- Zylinder in Millimetergröße: trimesh verschmolz nahe Punkte, der Körper war nicht mehr geschlossen. Jetzt in Einheitsgröße erzeugt und skaliert.

## Datensatz

`--design f5`: 8 Basen (Re 20–200, W/H 1–3) × 6 Features (h/H 0,1–0,5, w/H 0,2–1,5, b/W 0,3–0,8), dazu GCI auf einer Basis (n = 7 und 14 je H). 68 Fälle, auf dem Laptop mit 7 Workern grob 30–60 Minuten.
