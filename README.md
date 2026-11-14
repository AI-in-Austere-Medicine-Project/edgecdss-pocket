# EdgeCDSS Pocket

A wearable that gives a signed drug dose in millilitres by voice. No language model, no network, no screen.

Say "ketamine for moderate pain, IV, eighty kilos." It says "Ketamine, moderate to severe pain analgesia, IV, eighty kilos. Confirm?" Say "confirm." It says "Ketamine twenty milligrams. Dilute one mil of fifty in nine mils of normal saline. Four mils of the dilution, five per mil." It logs the time.

That is the signed 0.25 mg/kg. At the kit's 50 mg/mL vial it would be 0.4 mL, under the 0.5 mL that can be drawn reliably, so the volume comes from the signed dilution instead: 1 mL of the vial in 9 mL of normal saline, 5 mg/mL. The device says how to make it before it says how much to draw.

Part of the [AI in Austere Medicine Project](https://github.com/AI-in-Austere-Medicine-Project). The dose bank is signed in [EdgeCDSS](https://github.com/AI-in-Austere-Medicine-Project/pi-cloud-cdss) and exported here; Pocket signs nothing.

> Research prototype. Not validated for clinical use. Simulated scenarios only.

## The three rules

1. **Nothing on the device can say a number that was not signed.** Every dose, cap, dilution and vial strength comes from the exported signed bank. There is no model and no free-text path.
2. **Read-back before any dose.** The device repeats drug, indication, route and weight and acts only on "confirm."
3. **Every confirmed dose is logged with a time.** The log leaves the device only by deliberate export.

## Hardware (about $40)

| Part | Choice |
|---|---|
| Board | Raspberry Pi Zero 2 W |
| Audio | Any Bluetooth headset (mic + earpiece in one pairing); the headset button is push-to-talk |
| Power | 2,000 mAh LiPo with a charge/boost board; about a day |
| Storage | microSD, read-only root, separate log partition |
| Case | Printed, forearm strap or clip |

## Software

| Layer | Choice |
|---|---|
| OS | Raspberry Pi OS Lite 64-bit, boots to the service |
| Speech in | Vosk small English model with a **grammar** generated from the bank (drug names and aliases, indications, routes, numbers, control words). Nothing outside the grammar is recognised. |
| Engine | Python, ported from EdgeCDSS's pre-gate: signed lookup by drug, indication, route, population; caps; kit vial and signed dilution to mL; the weight and which-indication questions. Same tests. |
| Speech out | Piper small English voice with the EdgeCDSS spoken templates (numbers and units written out) |
| Content | `bank.json` exported from EdgeCDSS with every entry's source, page, quote, signer and date; `kit.json` with the declared vial strengths. The device refuses to start on an unsigned or EXAMPLE bank. |
| Log | Append-only JSON lines; export over USB on the bench |

## Vocabulary

Drug names and aliases from the bank; indication names from the bank; routes (IV, IO, IM, IN, PO, "line"); numbers, "kilos," "pounds," "estimated"; "child," "years"; conditions the medic can state ("burns," "crush injury," "head injury," "asthma"), each one found in the signed contraindications or cautions; control words: confirm, cancel, repeat, why, new patient, log, battery. About forty words plus numbers.

## Flow

- "New patient" clears weight and age and says so.
- A phrase with drug + indication (+ route, + weight) goes to the engine. A missing weight gets "Weight?"; a missing indication for a multi-indication drug gets "Which indication: pain or agitation?"; a name close to two drugs (ketamine / ketorolac) always asks.
- A stated condition that a signed contraindication names holds the dose: no read-back, no dose. "Succinylcholine, RSI, eighty kilos, burns" → "Held. Succinylcholine is contraindicated with burns. Rocuronium is the signed alternative." The alternative is another signed drug for the same indication that this patient's conditions do not hold. A contraindication the signed text itself qualifies ("relative", "unless", "except") is spoken after the dose instead.
- Read-back, then "confirm" → dose in mg and mL from the kit vial or signed dilution. Dose first, then only the cautions that name a condition the medic stated. Logged.
- "Why" speaks the source (quotes word for word), then every caution and contraindication. When no volume was given, a spoken caution leaves out what states a volume ("10 mL", "0.1 mL/kg"); concentrations ("1 mg/mL", "1:1,000") stay. The signed text in `bank.json` is unchanged.
- A stated vial that is the kit's signed vial ("fifty milligrams per mil" for ketamine) gives the volume; any other stated vial gives milligrams only. The words are compared with the signed vial's; nothing is computed from them.
- Unsigned drug: "No signed dose for magnesium." Nothing else.

## Build order

1. **Engine on the bench, no audio.** Port engine and tests; write the exporter in EdgeCDSS; typed phrases through the grammar parser; acceptance tests A–E below.
2. **Speech in.** Vosk with the generated grammar on a Zero 2 W over a Bluetooth headset; the typed tests become spoken tests; first noise measurements.
3. **Speech out and the flow.** Piper, read-back, confirm, dose, "why," log.
4. **Hardware and a day on battery.** Case, auto-reconnect to the headset on boot ("connected"), clean shutdown.
5. **Field matrix.** Vehicle, wind, gloves, whisper, accents; word error rate per condition; confidence threshold set from that data. Then the first personal build.

## Acceptance tests

- A1 "new patient" clears weight; the next dose asks for it, never reuses.
- B1 "ketamine five hundred milligrams" is read back as spoken; the engine's own dose is given; the spoken number is never computed on.
- C1 "keto" asks ketamine or ketorolac; no auto-resolution.
- C2 unsigned drug speaks the hold and nothing else.
- D1 read-back on 100 % of dose flows; "confirm" is the only word that proceeds.
- E1 unsigned or EXAMPLE bank: device announces it and refuses all dose flows.
- G1 "why" speaks the source for every entry; boot announces bank version and hash.

## Test bank (bench only)

A test bank is never a bank for patients. EdgeCDSS writes one only with `export_pocket_bank.py --test`: `bank-ems-test.json`, `kit-ems-test.json` and `manifest-ems-test.json` with `"test": true`. Its entries are unsigned and have status "test". The kit is the signed EMS kit. Pocket loads it only when started with `POCKET_TEST=1` (exactly `1`), and then it loads nothing else. Without that, anything marked test is refused, whatever its file names.

In test mode Pocket:
- says "Test set. Not for patient use." at boot and at the start of every read-back;
- puts `test: true` and the entry's `check_failed` reasons on every log record;
- says "Unverified." before a dose whose entry failed a transcription check or contradicts its own card;
- calls a test entry's range, cap and floor "test", never "signed".

Pocket does not read an entry's `kit_vial` yet. Until it does, an entry that names its vial (a strength, or "none") speaks milligrams only: "Milligrams only, no volume." An entry with a null `kit_vial`, and every PFC entry (they carry none), takes its volume from the drug's one signed vial, as before. This applies in any bank, test or signed.

    POCKET_TEST=1 python3 -m engine <dir holding bank-ems-test.json>

## Repo layout

```
edgecdss-pocket/
├── README.md
├── bank/            bank.json, kit.json (exported; versioned; hash in manifest)
├── engine/          dose engine + tests (ported from EdgeCDSS)
├── grammar/         generator: bank → Vosk grammar
├── voice/           vosk + piper glue, push-to-talk, templates
├── device/          OS image notes, service unit, Bluetooth pairing, power
└── tests/           acceptance tests A–G, replay corpus of phrases
```

## Licence

MIT. The bank carries the signatures and sources of the EdgeCDSS entries it was exported from.
