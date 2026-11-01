# The CORE sensor as a reference for HESTIA

*Release 2026.10.27. Why the core temperature of the CORE sensor is not "the
truth" when HESTIA is compared with field data, what the literature says
about its error, what this means for the Thermo Clinic results, and how the
suite deals with it.*

The Thermo Clinics compare HESTIA with a **CORE body temperature sensor**
(greenteg) worn on a chest strap and paired with a Garmin watch. CORE is
practical, but it is itself an estimate. Every model-minus-CORE difference
therefore contains two errors: the model's and the sensor's. This document
summarises what is known about the second one.

---

## 1. How CORE estimates core temperature

- CORE does **not** measure core temperature. It measures skin temperature
  and the heat flux through the skin under the sensor, plus ambient
  temperature, and, when paired, heart rate. An algorithm turns these into
  an estimated core temperature.
- The algorithm combines classical heat-transfer models with machine
  learning trained on thousands of points with pill, rectal and catheter
  references. It changes with firmware updates; the manufacturer asks
  studies to report the firmware version.
- **With heart rate** CORE switches to an "intense endurance sports" mode in
  which heart rate is used to anticipate changes of core temperature.
  **Without heart rate** it uses only the thermal signals; the manufacturer
  states a lag of 5 to 30 minutes. The suite's FIT reader decodes the CORE
  quality field and excludes recordings with too little heart-rate pairing
  (Emmen: runner L04, 21 % of the time).
- Manufacturer specification (as cited in Goulet et al. 2026): mean absolute
  deviation 0.21 °C, 95 % limits of agreement ±0.55 °C. This is a vendor
  figure, not an independent validation.

Two consequences matter for HESTIA:

1. Because CORE **uses heart rate**, its estimate is partly tied to relative
   effort (heart-rate reserve) by construction.
2. Because CORE **infers core temperature from the skin**, conditions that
   change skin heat flux (airflow over the chest while running, sweat, a
   cool day, clothing over the sensor) can bias it.

---

## 2. What the validation studies report

Bias = CORE minus reference; negative = CORE reads too low. Most studies
were read as abstracts only; see the sources at the end.

### 2.1 Against an ingestible (gastrointestinal) pill

| Study | Setting | Bias of CORE | Authors' conclusion |
|---|---|---|---|
| Jolicoeur Desroches et al. 2023, J Therm Biol | **running**, 5 km time trial at 30 °C, n = 12 | −0.30 to −0.49 °C at rest beforehand; 0.47 °C mean absolute difference during the trial; rate of rise underestimated by 0.0125 °C/min | "clinically relevant underestimation" |
| Goods et al. 2023, Eur J Sport Sci 23:1509 | **outdoor** field hockey in the heat, elite women, n = 19, 4 sessions | −0.06 to −0.34 °C per session; **underestimation grows with core temperature**; > 0.3 °C apart in 41–60 % of samples | not a valid substitute for the pill in the heat |
| Atkins et al. 2022, conference abstract | indoor, increasing intensity, warm clothing, n = 20 | −0.3 °C (limits −0.61 to +0.03 °C); low from 15 min of exercise | underestimates, margin "relatively small" |
| Januário 2023, MSc thesis | cycling at 32 °C, n = 16 | +0.01 °C (limits −0.35 to +0.38 °C) | valid and reliable |
| Kaltsatou et al. 2024, Sensors 24:807 | heart-failure patients, treadmill test at 28 °C (CALERA version) | about 0 on average, limits about ±1.0 °C; weak association during exercise | poor agreement |
| Goulet et al. 2026, Sensors 26:5042 | rest, cold-water hyperhydration, n = 11 | pill fell 0.76 °C, CORE 0.09 °C; CORE up to +0.9 °C too high during cooling | misses internal cooling |

### 2.2 Against a rectal probe

| Study | Setting | Bias of CORE | Authors' conclusion |
|---|---|---|---|
| Verdel et al. 2021, Sensors 21:5932 | laboratory cycling at 19 °C and 31 °C | +0.23 °C (limits −0.38 to +0.72, 19 °C), −0.10 °C (−0.62 to +0.59, 31 °C); 51 and 45 % within 0.3 °C | not sufficiently valid (0.3 °C criterion; disputed by the manufacturer) |
| Daanen, Kohlen & Teunissen 2023, J Therm Biol 112:103480 | climate chamber 18 °C, exercise to exhaustion, n = 9 | tends to overestimate throughout; about +0.2 °C at peak (computed from the reported means) | use with care |
| Field observation, Thermo Clinic organiser (oral, 26 Oct 2026) | own runs, details not yet available | consistently about −0.5 °C | – |

### 2.3 Pill and rectal probe themselves

Pill and rectal temperature agree within about 0.1–0.2 °C on average:
−0.19 °C during outdoor exercise in the heat (Casa et al. 2007, the only
device within ±0.27 °C), a systematic difference of a little over 0.1 °C
(Byrne & Lim 2007, review), 0.1–0.2 °C with wide individual scatter during
supramaximal intermittent exercise (Castle et al. 2002). A pill is affected
by cold drinks shortly before and by ingestion timing; a rectal probe lags
during fast changes. A CORE-to-reference difference of 0.3–0.5 °C is
therefore most likely a CORE error.

### 2.4 Synthesis

- **Running and exercise in the heat** (the only studies with running or
  field sport): CORE reads **0.1–0.5 °C too low**, more so at higher core
  temperature, and shows a fast rise too slowly.
- **Laboratory cycling against a rectal probe:** close to zero or slightly
  high (+0.2 °C).
- **Single readings** scatter widely: for one runner a CORE value is not
  more accurate than about ±0.5 °C.
- No study covers outdoor running at moderate temperature as in the clinics.
  A plausible but untested explanation for the running/cycling difference is
  airflow and sweat over the chest, which change the skin heat flux from
  which CORE computes.

**Working assumption for the clinics** (outdoor running, CORE with heart
rate): CORE reads **0.2–0.5 °C too low**, at the peak rather more than less.
This is an inference from the studies above, not a measurement.

---

## 3. What this means for the Emmen clinic (17 Oct 2026, WBGT 12–13)

### 3.1 Group level

| Assumption about CORE | Model minus true core, peak | Model minus true core, mean during run |
|---|---|---|
| CORE correct | +0.35 °C | +0.19 °C |
| CORE 0.2 °C low | +0.15 °C | −0.01 °C |
| CORE 0.3 °C low | +0.05 °C | −0.11 °C |
| CORE 0.5 °C low | −0.15 °C | −0.31 °C |

If the working assumption holds, HESTIA is close to the true peak core
temperature at group level, not a third of a degree too high. "The model errs on
the safe side" is therefore not an established conclusion.

### 3.2 Individual level: what each one follows

- The **CORE peak rises with relative effort** (% heart-rate reserve): about
  +0.11 °C per 10 % (r = 0.68, p = 0.03, 10 runners), and **not with running
  speed** (r = −0.25).
- The **model peak rises with running speed** (r = 0.62, p = 0.05), and not
  with relative effort (r = 0.08).
- Modern thermophysiology holds that the rise of core temperature is set by
  **heat production per kg body mass**, not by relative intensity: at equal
  W/kg, fit and unfit people warm equally (Jay et al. 2011: 0.87 °C in both
  groups at ~7 W/kg; Cramer & Jay 2014). The classic relation with relative
  intensity (Saltin & Hermansen 1966) arises because fitter people produce
  more heat per kg at the same percentage. In running, heat production per kg
  is mainly a matter of speed.
- The model thus behaves as Jay and Cramer predict; CORE's link with
  heart-rate reserve may partly be built into its own algorithm. With ten
  runners on one cool day this is an indication, not proof.

### 3.3 The model's own error on a cool day

HESTIA itself runs too warm in cool weather. In JOS-3 a skin colder than its
set point strongly suppresses skin blood flow and sweating; during running
in cool weather the model skin ends up far below set point and the core
settles higher in the cold than at 20 °C, contrary to the "prescriptive zone"
in which exercise core temperature hardly depends on ambient temperature
(Nielsen 1938; Lind 1963). JOS-3 was validated only at rest (Takahashi et
al. 2020). In Emmen the model chest skin was on average **0.6 °C colder**
than the CORE skin reading (−2.7 to +2.2 °C per runner; CORE reads the skin
under the sensor, which may be warmer than bare skin). With the cold-skin
signal limited to 2 K (diagnostic, `jos3_leeftijd.COLD_SKIN_LIMIT_K`) the
model skin is 0.8 °C warmer than CORE's and the model peak core comes to
+0.16 °C above CORE. The sun on the clinic day (globe temperature by the
Liljegren et al. 2008 energy balance) accounts for much of the skin
temperature, so this clinic gives little evidence for a cold-skin error.

In Emmen, two errors may have partly cancelled: a model that may run
too warm on a cool day and a sensor that reads too low while running. The
true core temperature most likely lies between the two model variants (B3
and B4). Only a reference measurement can settle this.

The cold-skin error is below 0.1 °C from **WBGT ≈ 18** at race intensity
(≈ 20 for slow running, ≈ 16 at 90 % VO2max) and 0.6–1.3 °C below WBGT 12.
Heat-risk results at warm events (Dam tot Damloop 2024: WBGT ≈ 21) are hardly
affected, and the calibration does not move when the limit is switched on
(`CHANGELOG.md`, 2026-10-27).

---

## 4. How the suite handles it

- **No model change on the basis of CORE alone.** The cold-skin limit exists
  as a setting, **off by default**; the decision waits for a clinic with a
  reference measurement.
- **Clinic comparison** (`clinic_validatie.py`): variants B1–B3 as
  pre-registered, plus **B4** (B3 with the cold-skin limit, exploratory), and
  the measure **`huid_borst_bias`** (model chest skin minus CORE skin). Both
  are marked exploratory in `criteria.json` (version 2026-10-27).
- **One-run analysis** (`fit_loop.py`) and the clinic report state the CORE
  caveat next to every core-temperature comparison, and the cold-skin caveat
  when the WBGT was below 18.

---

## 5. Real-time display and safety

CORE is not only a research logger. Paired with a Garmin watch (and other
sports watches), the CORE data field shows the estimated core temperature
**live during exercise**, optionally alternating with a "Heat Strain Index"
of 0–10 ("how hard your body is working to stay cool"; greenteg). Workplace
systems go further: Kenzen sends vibration and app alerts to the worker and
a dashboard alert to the supervisor when the predicted core temperature
"approaches unsafe levels", followed by a "back to work" alert.

This raises a safety question that matters more than the accuracy of the
average:

1. **The error is largest where it matters most.** CORE's underestimation
   grows with core temperature (Goods et al. 2023); the heart-rate algorithm
   ECTemp loses sensitivity above about 39 °C (de Korte et al. 2022: bias at
   peak −0.02 °C but limits ±0.92 °C). A runner who reads 39.0 °C may be
   at 39.5 °C or higher.
2. **A number on the wrist is read as a measurement.** It invites "still
   fine, carry on". In exertional heat stroke the central nervous system is
   affected; judgement, not only the body, fails. A reassuring number may
   then outweigh the warning signs.
3. **Symptoms are not a safe substitute either.** Mental status varies
   unpredictably between heat-stroke patients (Lopez et al. 2024); the
   clinical reference remains rectal temperature, and other routes
   (tympanic, oral, skin, axillary) are invalid in an exercising person
   (Korey Stringer Institute).
4. **The manufacturer's own position.** greenteg's US disclaimer states that
   CORE "is not a medical device and cannot be used for medical diagnoses"
   and "cannot be used as a replacement for the standard of care". Its
   Heat Strain Index page carries no such warning.
5. **Validation of warning systems is scarce.** One prospective laboratory
   study of an alert system (2B-Cool, Med Sci Sports Exerc 2023, n = 22,
   rectal reference) reported 98 % sensitivity and 81 % specificity at a
   38.5 °C threshold; none of the field studies of CORE, ECTemp or Kenzen
   tested alerts at the temperatures of heat stroke. Workplace guidance
   (National Safety Council 2024; Morrissey et al. 2026) treats wearables
   as a supplement to heat plans, training and clinical judgement, never a
   replacement.

**Consequences for the Thermo Clinics and for events**

- Tell participants that the CORE value is an estimate with about ±0.5 °C
  error per reading, likely too low when the core is hot. The trend is more
  useful than the number.
- A "good" value is never a reason to continue; symptoms (confusion,
  dizziness, loss of coordination) always take priority.
- Medical teams at events should not rely on wearable readings for triage
  or for stopping cooling; rectal temperature remains the reference.
- The same applies to the suite's own colour signal in the personal runner
  report (independent review, finding M7): a model "green" can give the
  same false reassurance.

## 6. Recommendations for the next Thermo Clinics

1. **Reference measurement:** an ingestible pill for part of the runners
   (6–10), following the protocol of a group with experience. Model, CORE and
   pill can then be compared at the same time. A pill is far more acceptable
   to runners than a rectal probe.
2. **Cold drinks:** no cold drinks in the hours before for runners with a
   pill, or record exactly what and when (Goulet et al. 2026).
3. **Heart rate:** make sure CORE receives heart rate all the time,
   preferably from a chest strap rather than the wrist.
4. **Record:** CORE firmware version, sensor position and fixation, clothing
   over the sensor, wind and sun.
5. **Spread in effort and speed:** let runners run deliberately at different
   speeds, or the same runner twice, so that the dependence on heat
   production can be tested.
6. **Pre-start:** let all runners wait at the same place (inside or outside)
   and record it; in Emmen the model assumed outdoors while the runners sat
   inside.
7. **A warm day** (WBGT above ~18): core temperatures are higher, the
   sensor's error is largest there according to the studies, the model's
   cold-skin error is absent, and it is the range HESTIA is meant for.
8. **Pre-register** the assumed sensor error and acceptable differences in
   `criteria.json` before the clinic.

---

## Sources

- Atkins C, Handler G, Mendez C, Molina A, Outlaw L, Becker MG, Schubert MM. Validity of a novel sensor for noninvasive measurement of core body temperature in humans during exercise. Int J Exerc Sci Conf Proc 2022;14(2).
- Byrne C, Lim CL. The ingestible telemetric body core temperature sensor: a review of validity and exercise applications. Br J Sports Med 2007;41(3):126-133.
- Casa DJ, Becker SM, Ganio MS, et al. Validity of devices that assess body temperature during outdoor exercise in the heat. J Athl Train 2007;42(3):333-342.
- Castle P, Spencer M, Webborn N, Maxwell N. Bias and limits of agreement between rectal and telemetry pill measurement of core temperature during intermittent supramaximal exercise under heat stress. Conference abstract, University of Brighton, 2002.
- Cramer MN, Jay O. Selecting the correct exercise intensity for unbiased comparisons of thermoregulatory responses between groups of different mass and surface area. J Appl Physiol 2014;116(9):1123-1132.
- Daanen HAM, Kohlen V, Teunissen LPJ. Heat flux systems for body core temperature assessment during exercise. J Therm Biol 2023;112:103480. doi:10.1016/j.jtherbio.2023.103480.
- Goods PSR, Maloney P, Miller J, Jennings D, Fahey-Gilmour J, Peeling P, Galna B. Concurrent validity of the CORE wearable sensor with BodyCap temperature pill to assess core body temperature during an elite women's field hockey heat training camp. Eur J Sport Sci 2023;23(8):1509-1517. doi:10.1080/17461391.2023.2193953.
- Goulet EDB, Jolicoeur Desroches A, Deshayes TA, et al. Validity of the CORE wearable sensor during internal cooling induced by hyperhydration with cold water at rest. Sensors 2026;26(16):5042.
- greenteg (manufacturer). Core body temperature; On CORE's accuracy; Public statement on Verdel et al. 2021. corebodytemp.com and greenteg.com, accessed 26-27 Oct 2026.
- greenteg. Disclaimer for use in the United States of America; Garmin Heat Strain Index. corebodytemp.com, accessed 28 Oct 2026.
- Januário WM. Validity and reliability of two core temperature measurement techniques during physical exercise in the heat: CORE sensor and Exergen TAT-5000. MSc thesis, Universidade Federal de Viçosa, 2023. doi:10.47328/ufvbbt.2024.015.
- Jay O, Bain AR, Deren TM, Sacheli M, Cramer MN. Large differences in peak oxygen uptake do not independently alter changes in core temperature and sweating during exercise. Am J Physiol Regul Integr Comp Physiol 2011.
- Jolicoeur Desroches A, Naulleau C, Deshayes TA, Pancrate T, Goulet EDB. CORE wearable sensor: comparison against gastrointestinal temperature during cold water ingestion and a 5 km running time-trial. J Therm Biol 2023 (also SSRN 4403113).
- Kaltsatou A, Anifanti M, Flouris AD, Xiromerisiou G, Kouidi E. Validity of the CALERA research sensor to assess body core temperature during maximum exercise in patients with heart failure. Sensors 2024;24(3):807. doi:10.3390/s24030807.
- Kenzen heat monitoring system (trade press: Pit & Quarry), accessed 28 Oct 2026.
- Korey Stringer Institute. An athlete's guide to exertional heat stroke (information sheet, updated 2019).
- de Korte JQ, Veenstra BJ, van Rijswick M, Derksen EJK, Hopman MTE, Bongers CCWG, Eijsvogels TMH. A heart rate based algorithm to estimate core temperature responses in elite athletes exercising in the heat. Front Sports Act Living 2022;4:882254. doi:10.3389/fspor.2022.882254.
- Lind AR. A physiological criterion for setting thermal environmental limits for everyday work. J Appl Physiol 1963;18:51-56.
- Lopez RM, Nolan JK, Yeargin SW, Scarneo-Miller SE, Casa DJ, Jardine J. Comparison of core temperature and mental status of two runners experiencing exertional heat stroke after a road race. J Sci Med Sport 2024 (in press). doi:10.1016/j.jsams.2024.12.003.
- Morrissey MC, Lee JKW, Rollo I, Pitsiladis Y. Leveraging wearables to safeguard workers in a hotter climate. Front Public Health 2026;14:1867796.
- National Safety Council. Best practices and the use of vital signs monitoring for heat stress mitigation. Work to Zero, 2024.
- Nielsen M. Die Regulation der Körpertemperatur bei Muskelarbeit. Skand Arch Physiol 1938;79:193-230 (as summarised in National Academies 1993, Nutritional Needs in Hot Environments, ch. 6).
- Laxminarayan S, Hornby S, Belval LN, Giersch GEW, Morrissey MC, Casa DJ, Reifman J. Prospective validation of 2B-Cool: integrating wearables and individualized predictive analytics to reduce heat injuries. Med Sci Sports Exerc 2023;55(4):751-764. doi:10.1249/MSS.0000000000003093.
- Saltin B, Hermansen L. Esophageal, rectal, and muscle temperature during exercise. J Appl Physiol 1966;21(6):1757-1762.
- Takahashi Y, Nomoto A, Yoda S, et al. Thermoregulation model JOS-3 with new open source code. Energy Build 2020;231:110575.
- Verdel N, Podlogar T, Ciuha U, Holmberg HC, Debevec T, Supej M. Reliability and validity of the CORE sensor to assess core body temperature during cycling exercise. Sensors 2021;21(17):5932. doi:10.3390/s21175932.

Most of these were read as abstracts; for Jolicoeur Desroches et al. part of
the figures come from the SSRN version and a secondary summary. Full Dutch
report: "Hoe nauwkeurig is de CORE-sensor bij hardlopen?" (27 Oct 2026).
