# Toetsplan PYROX — leeftijdsgradiënt Parijs 2003 (vastgelegd 2026-11-23, vóór de toets)

Dit plan is vastgelegd voordat de toets met de nieuwe PYROX-versie is uitgevoerd.
Beslissingen over het model zijn genomen door Koos de Boer; Claude (Anthropic) heeft
als assistent het plan uitgeschreven en zal de toets uitvoeren.

## Wat wordt getoetst

Optie B: elke PYROX-groep wordt doorgerekend als een ensemble van leden die verschillen
in hittebestendigheid (heterogeniteit binnen de groep). Per lid worden de drie
beschermende parameters (`max_acclimatization_capacity`, `recovery_threshold`,
`base_recovery_rate`) met dezelfde factor f vermenigvuldigd. f is lognormaal verdeeld
met mediaan 1 en variatiecoëfficiënt CV. Capaciteit wordt begrensd op 0,95. Het ensemble
bestaat uit 41 leden op de midden-kwantielen van die verdeling (deterministisch, geen
toeval). De groepsuitkomst is het gemiddelde over de leden; daarnaast de fractie leden
in de noodsituatie (≥ 90 % van de kritieke grens).

## Vooraf vastgelegde keuzes

- **CV = 0,30** (hoofdtoets). Onderbouwing: de onderlinge variatie in temperatuurregulatie
  is groot; bij gelijke warmteproductie verschilt de stijging van de kerntemperatuur tussen
  personen tot 1,1–1,9 °C (Cramer & Jay 2015, J Appl Physiol, PMC4628991). Een directe maat voor de spreiding van
  "beschermende capaciteit" bestaat niet; 0,30 is het midden van een redelijk bereik.
  CV = 0,20 en 0,40 worden altijd mee gerapporteerd als gevoeligheid; er wordt niet achteraf
  de best passende waarde gekozen.
- **Gebeurtenis:** Parijs augustus 2003 zoals in de suite (`paris2003.py`:
  `paris_2003_heat_loads(per_degree=0.10)`, `pre_heatwave_heat_load = loads[0]`,
  slaapkwaliteit uit de gemeten nachtminima, "night_after").
- **Groepen ↔ leeftijd:** `adults_18_45` ↔ 15–44 j, `middle_aged_45_65` ↔ 45–64 j,
  `elderly_65_85` ↔ 65–84 j, `very_elderly_85plus` ↔ 85+ j.
- **Gemeten maat (Fouillet et al. 2006, tabel 1, O/E, 1–20 aug 2003):** overmaat E = O/E − 1:
  15–44 j: 0,13 (15–34: 1,1; 35–44: 1,2) · 45–64 j: 0,30 · 65–84 j: 0,50 (1,4 en 1,6) ·
  85+ j: 0,85 (1,8 en 2,0).
- **Modelmaat (primair):** F = fractie van de ensembleleden die tijdens de periode de
  noodsituatie bereikt (≥ 90 % van de kritieke grens). Aanname: de oversterfte in een groep
  is evenredig met het aandeel leden dat ontspoort.
- **Modelmaat (secundair):** piek van de gemiddelde belasting als % van de kritieke grens.

## Criteria (hoofdtoets, CV = 0,30)

1. **Volgorde:** F stijgt strikt: 15–44 < 45–64 < 65–84 < 85+.
2. **Geen nul bij jong:** F(15–44) > 0.
3. **Verhoudingen:** voor elke groep ligt F_g / F_65–84 binnen een factor 2 van
   E_g / E_65–84 (gemeten: 0,26 · 0,60 · 1 · 1,70).
4. **Vorm in de tijd niet slechter:** de correlatie (Pearson) tussen de dagelijkse gemiddelde
   belasting van 65–84 j en 85+ j en de dagelijkse oversterfte (Fouillet, `paris_2003_excess_deaths`)
   is niet meer dan 0,05 lager dan met het huidige model.

De toets slaagt als alle vier de criteria gelden. Elk criterium wordt afzonderlijk gerapporteerd.

## Openheid over de verkenning

Vóór dit plan is één verkennende berekening gedaan (CV 0,2 / 0,3 / 0,4, dezelfde opzet).
De uitkomst daarvan was bekend bij het vastleggen van dit plan. De keuze CV = 0,30 is daarop
niet aangepast (het was vooraf het midden van het bereik), maar de toets is daardoor niet
volledig blind. Een onafhankelijke toets blijft nodig, bijvoorbeeld met de leeftijdsverdeling
van een andere hittegolf (Frankrijk 2006, VK 2022).

## Wat niet verandert

De drie paper-groepen houden hun parameters. Het enkelvoudige model (`PyroxModel`) blijft
ongewijzigd en blijft de "typische" (mediane) deelnemer beschrijven; `verify.py` toetst dat
model. De tabbladen Regimes, Terugkoppeling en Kantelpunt in de UI tonen dit mediane lid.
