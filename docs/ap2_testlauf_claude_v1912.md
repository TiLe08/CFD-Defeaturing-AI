# AP2 / Gate 1: Testlauf in Claudes Umgebung (OpenFOAM v1912, ohne Function Objects)

Referenzwerte zum Vergleich mit deinem ersten Lauf. Laufzeiten gelten für Claudes Cloud-Container (4 Kerne, 3 Worker), nicht für deinen Laptop.

## 1. Läuft die Pipeline?

14 Fälle: solved 14. checkMesh OK: 14/14. Konvergiert: 13/14.

- nicht konvergiert: f1_ap2_b000_with_rib_h0.1 (5000 Iterationen, Residuen {'Ux': 1.317437748e-07, 'Uy': 5.081954073e-06, 'p': 5.840582072e-08})
- Hinweis: Δp teils aus dem Endfeld statt aus der Zeitreihe (Lauf ohne Function Objects), Iterationsstreuung dann unbekannt.

## 2. Laufzeit

Fälle mit Feature: Median 2.0 s (max. 54.0 s) bei Median 8731 Zellen. Bei 900 Läufen und 3 parallelen Workern ergibt das etwa 0.2 h reine Rechenzeit. Die Laufzeit gilt für Fälle wie diesen (Re, Netz); höhere Re und turbulente Familien sind teurer.

## 3. Feature-Effekt gegen numerischen Fehler

Nullversuche (Abweichung von Δp ohne Feature, relativ):

- null_nobox: -0.3843%
- null_shift: -0.0086%

GCI (Celik et al. 2008; fein/mittel/grob = 15613/8716/4690 Zellen, r21 = 1.34, r32 = 1.36):

- Δp ohne Feature: Werte 0.00910673 / 0.00898346 / 0.00881813, p = 0.77, GCI_fein = 6.70%
- ΔQ_rel der GCI-Nut: Werte -0.1425% / -0.1381% / -0.1534%, oszillierend, Unsicherheit (halbe Spannweite) ±0.0076%

Numerische Unsicherheit von ΔQ_rel (größer aus Box-Verschiebung und GCI): ±0.0086%. Der Versuch ohne Verfeinerungsbox zeigt, wie groß der Fehler ohne konsistente Vernetzung wäre, und geht deshalb nicht in die Unsicherheit ein.

| Feature | Typ | h/H | ΔQ_rel | Unsicherheit | auflösbar (>2u) | relevant (τ = 1 %) | Label unsicher | h⁺ | ausgeschlossen |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| f1_ap2_b000_with_groove_h0.05 | groove | 0.05 | -0.1209% | ±0.0086% | ja | nein | nein | 1.21 |  |
| f1_ap2_b000_with_groove_h0.1 | groove | 0.1 | -0.1380% | ±0.0086% | ja | nein | nein | 2.43 |  |
| f1_ap2_b000_with_groove_h0.2 | groove | 0.2 | -0.1381% | ±0.0086% | ja | nein | nein | 4.85 |  |
| f1_ap2_b000_with_rib_h0.05 | rib | 0.05 | +0.4528% | ±0.0086% | ja | nein | nein | 1.21 |  |
| f1_ap2_b000_with_rib_h0.1 | rib | 0.1 | +1.2855% | ±0.0086% | ja | ja | nein | 2.43 | not converged |
| f1_ap2_b000_with_rib_h0.2 | rib | 0.2 | +4.4142% | ±0.0086% | ja | ja | nein | 4.85 |  |
