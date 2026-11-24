# File map

Every file in edgecdss-pocket, as of Pocket main `11370bc` (2026-11-24). This is step 1 of a restructure: a map only. Nothing was moved or changed, and no new structure is proposed here. `tests/test_file_map.py` fails if a file is added or removed without this map being updated.

## How to read it

**Made by**
- *hand*: written and edited by a person.
- *generated*: written by a program, which is named. Do not edit it by hand; run the program again.
- *unused*: nothing runs it any more.

**Used by**
- **S**, the device service: what the board runs from power-up (`pocket.service` → `voice/autostart.py`).
- **I**, the install script: `device/install.sh` copies, runs or checks it.
- **W**, the web page pin: the portal's `/pocket` and `/pocket/teach` pages import or read it from the pinned checkout.
- **T**, the tests.
- **H**, run by hand: a tool or document a person runs or reads.

✍ marks **signed or ruled content**: files that hold what you signed or ruled on. Change these only with your signature or ruling.

---

## Top level

| File | What it does | Made by | Used by |
|---|---|---|---|
| `README.md` | The front page: the three rules, the hardware, how to install, the vocabulary, a worked example. ✍ The three rules are yours. | hand | H, T (`test_readme*.py` check its header and worked example) |
| `ROADMAP.md` | The planned sections of work and how to get involved. | hand | H |
| `LICENSE` | MIT licence for the code. | hand | H |
| `pytest.ini` | Tells the test runner the three test folders and to import from the repo root. | hand | T |
| `.gitignore` | Keeps out of the repo: caches, `bench-out/` (recordings, including your clips), `models/`, `replay-out/`. | hand | everything (git) |

## `bank/`: the signed drug list and procedures

The only drug content Pocket can speak. Nothing else in the repo holds a dose.

### `bank/ems/`: the one drug list in use (owner, 2026-11-23)

| File | What it does | Made by | Used by |
|---|---|---|---|
| `bank.json` | ✍ **The drug entries.** 178 signed entries for 29 drugs: dose, route, indication, population, weight floor, cap, cautions, and the page and quote from the formulary. Also lists the entries signed but silent (28) and the rows with no signed dose (166). Each entry records how it was signed: individually read (46) or bulk-signed without item review (160). | generated: EdgeCDSS `export_pocket_bank.py`, then signed by `~/formulary/ems_full/sign_bulk.py` (kept outside the repo) | S, W, T |
| `kit.json` | ✍ **The vials.** 26 vials (drug, strength, volume) that a volume in mL may be worked out from, plus the four strengths you declared as the standard product (owner-declared, not read from the kit). | generated (as above), with your declarations | S, W, T |
| `manifest.json` | ✍ **The signature record.** Who signed and when, the counts, the EdgeCDSS commit the list came from, and fingerprints (sha256) of `bank.json` and `kit.json`, so Pocket refuses a list that was changed after signing. | generated (as above) | S, W, T |
| `procedures.json` | ✍ **The signed procedures.** RSI and failed airway: every step's text, order, branches and dose links. Also your rulings Q1–Q10, struck and unspoken steps, the dated amendments (6 and 6b at fixed doses with the original JTS text kept), and the child hold ("No signed RSI steps for a child."). | hand (edited only to carry a signature or ruling) | S, W, T |

### `bank/retired/pfc/`: the old PFC list, retired 2026-11-23

Kept unchanged; never loaded on the device or the web. Pocket refuses it unless a test asks for it by name.

| File | What it does | Made by | Used by |
|---|---|---|---|
| `RETIRED.json` | ✍ Your retirement decision: the date, what the list was, and that only tests load it. | hand | S, W (Pocket refuses the folder because of it), T |
| `bank.json` | ✍ (formerly) The old PFC drug entries. | generated: EdgeCDSS export, before 2026-11-23 | T only, as test data |
| `kit.json` | ✍ (formerly) The old PFC vials. | generated (as above) | T only |
| `manifest.json` | ✍ (formerly) The old PFC signature record. | generated (as above) | T only |
| `procedures.json` | ✍ (formerly) The RSI and failed-airway steps as signed on 2026-11-20. The EMS copy says it was taken from this file. | hand | T only |

## `device/`: setting up the board

| File | What it does | Made by | Used by |
|---|---|---|---|
| `install.sh` | One command that sets up a fresh Radxa. It installs packages and Bluetooth audio, sets up Python with Vosk (hearing) and Piper (speaking), downloads and checks the models, pairs the speaker, makes the card safe to lose power, checks that the grammar matches the model and the drug list, and starts Pocket at boot. | hand | I (it *is* the install), T |
| `pocket.service` | The instruction to the board's start-up system to run Pocket at power-up and restart it if it stops. | hand (install fills in the user and home folder) | I, S, T |
| `pocket-wifi-up` | A small script that joins the saved Wi-Fi if the board has not (the hidden network is otherwise slow or never found). Pocket itself needs no network. | hand | I, T |
| `pocket-wifi-up.service` | Runs the Wi-Fi script once. | hand | I, T |
| `pocket-wifi-up.timer` | Runs the Wi-Fi script every 30 seconds. | hand | I, T |
| `RADXA.md` | Board notes: which board and image, setup steps, what was measured (memory, hearing on your voice), the voice session, how each word is said, and power-up and power-off. | hand | H |
| `setup_voice.sh` | Set up hearing on the **Raspberry Pi Zero 2 W**: Vosk, the model and the grammar. | hand | **unused**: that board was dropped (below the memory floor); `install.sh` does this on the Radxa |
| `memory.sh` | A memory guard (swap file and a memory ceiling) for the **Pi Zero 2 W**. | hand | **unused** (Pi Zero only) |

## `docs/`

| File | What it does | Made by | Used by |
|---|---|---|---|
| `WORK_ORDER.md` | ✍ **Your standing rules and owner rules** (including the PL/OLMC rule, 2026-11-23) and the dated log of every ruling and what changed. | hand | H |
| `BOARDS.md` | Boards tried: why the Pi Zero 2 W was dropped and the Radxa chosen. | hand | H |
| `pocket-board.jpg` | Photo of the board, shown in the README. | hand (photo) | H (README) |
| `FILE_MAP.md` | This map. | hand | H, T (`test_file_map.py`) |

## `engine/`: the clinical logic (no audio)

Takes words and gives what to say. It is the same on the board, on the web and in the tests.

| File | What it does | Made by | Used by |
|---|---|---|---|
| `__init__.py` | Empty; marks the folder as code. | hand | S, W, T |
| `__main__.py` | Type phrases at a keyboard and see the answers (`python3 -m engine`). | hand | H |
| `bank.py` | **Loads the drug list or refuses it.** It checks the signature fingerprints and that every entry is signed and complete. It refuses the retired PFC list, and refuses the bench test list unless `POCKET_TEST=1`. | hand | S, W, I (the grammar check), T |
| `contracts.py` | **The dose arithmetic,** ported from EdgeCDSS: per-kg times weight, caps, minimum doses, ranges, age limits, adult or child preference. | hand (port) | S, W, T |
| `vials.py` | **Dose to mL,** only from a signed vial in `kit.json`. It rounds by band and adds "Use a one mil syringe." under 0.5 mL; there is no dilution. | hand (port) | S, W, T |
| `words.py` | Numbers and units written out as spoken words ("two hundred milligrams"). ✍ `SAY_AS` holds your choices of how hard names are said. | hand | S, W, T |
| `procedures.py` | **Loads the signed procedures or refuses them.** A procedure loads only if wholly signed: every step present, every dose link exact, a child hold complete with line, owner, date and why. | hand | S, W, T |
| `session.py` | **One patient conversation.** It asks the missing questions (weight, indication, route, which entry), refuses what is not signed, reads back, waits for "confirm", gives the dose, then the cautions you ruled are said. It also covers "why", "repeat", the home menu and help, stepping through RSI, the child hold, and leaving out PL/OLMC text. ✍ The lines it speaks that you worded (home line, help, holds) are written here. | hand | S, W, T |
| `tests/PORTED.md` | What was ported from EdgeCDSS's tests and what was not. | hand | H |
| `tests/test_contracts_ported.py` | EdgeCDSS's dose-arithmetic tests, ported with their cases and values. Runs on the retired PFC list. | hand | T |
| `tests/test_pregate_ported.py` | EdgeCDSS's question-asking and hold tests, ported. | hand | T |
| `tests/test_vials_ported.py` | EdgeCDSS's dose-to-mL tests, ported. | hand | T |

## `grammar/`: which words Pocket knows and how it reads them

| File | What it does | Made by | Used by |
|---|---|---|---|
| `__init__.py` | Empty; marks the folder as code. | hand | S, W, T |
| `vocabulary.py` | **Builds the word list from the drug list:** drug names, common names (narcan), indications, routes, commands, numbers. A name close to two drugs is never guessed. | hand | S, W, T |
| `parser.py` | **Reads a phrase into slots** (drug, indication, route, weight, age, command). One word outside the list and the whole phrase is refused; nothing is corrected or guessed. A spoken dose is never read as a number. | hand | S, W, T |
| `confusable.json` | ✍ Pairs that sound alike (from your clips). Hearing either one asks "X or Y?" first. | hand (your ruling, 2026-11-15) | S, W, T |
| `sounds_like.json` | ✍ (ruled) **Sound-alike spellings** for drug names the hearing model does not know ("pralidoxime" heard as words it does know), plus the record of spellings dropped by your rulings. | generated: `voice/tools/make_spellings.py` and `voice/tools/teach_spellings.py --apply`, with hand edits for rulings | S, W, T |
| `vosk_grammar.json` | **The exact list of words the hearing model is allowed to hear** (738), with a fingerprint of the drug list and the model it was built for. | generated: `python -m voice.grammar MODEL` (also rewritten by `teach_spellings.py --apply`) | S, W, I (checked against model and list), T |

## `voice/`: hearing and speaking

| File | What it does | Made by | Used by |
|---|---|---|---|
| `__init__.py` | Empty; marks the folder as code. | hand | S, W, T |
| `autostart.py` | **What the board runs at power-up.** Loads the models once, waits for the speaker and button, and runs the voice session for as long as there is power, coping with the speaker coming and going. | hand | S, T |
| `device.py` | **The push-to-talk loop:** press, hear the beep, speak, release; the session answers aloud. Also `--typed`: type instead of speaking. | hand | S (through `autostart.py`), H, T |
| `listen.py` | **The microphone and the button.** The mic stays open; speech between press and release (plus a short lead-in) goes to hearing. | hand | S, T |
| `hear.py` | **Turns speech into words:** two decoders on the same audio, one with the sound-alike spellings and one without; it picks the one that reads cleanly. A command word ("confirm") is only ever taken from the spelled one. | hand | S, W, T |
| `spoken.py` | Joins spelled-out letters back into a name ("t x a" → TXA) and maps sound-alike spellings back to the drug name, before the parser. | hand | S, W, T |
| `speak.py` | **Speech out:** Piper says one sentence while making the next; a button press stops it. | hand | S, T |
| `grammar.py` | Builds `grammar/vosk_grammar.json` from the drug list and the model. It also gives the model's fingerprint (used by install and the web page). | hand | I, W, T, H |
| `bench.py` | Plays the replay phrases through the hearing model and scores them (used for the 2026-11-11 gate on your voice). | hand | H (`device/RADXA.md`) |
| `dryrun_drugs.json` | **Result of the drug-name hearing check:** every signed drug name said by three synthetic voices; heard 242 of 258, none as another drug. The teach page stars what was missed. | generated: `voice/tools/dryrun_drugs.py score` | W (teach page), T |
| `dryrun_words.json` | **Result of the hearing check for routes, procedures and commands:** 111 of 123 heard ("no" is missed in every voice). The teach page stars what was missed. | generated: `voice/tools/dryrun_words.py score` | W (teach page), T |
| `tests/__init__.py` | Empty; marks the folder as code. | hand | T |
| `tests/test_sounds_like.py` | The sound-alike spellings follow your rules: only words the model knows, never a word the parser would read as something else. | hand | T |
| `tests/test_spoken.py` | Hearing pieces that need no microphone or model: the letter joining and the grammar contents. | hand | T |

### `voice/tools/`: developer tools (not on the device's path)

| File | What it does | Made by | Used by |
|---|---|---|---|
| `__init__.py` | Empty; marks the folder as code. | hand | W, T |
| `dryrun_drugs.py` | Makes and scores the drug-name hearing check (writes `voice/dryrun_drugs.json`). | hand | H, W (the teach page reads its voice list and file location), T |
| `dryrun_words.py` | The same check for routes, procedures and commands (writes `voice/dryrun_words.json`). | hand | H, T |
| `synth_kokoro.py` | Makes the synthetic voice clips for the checks, using EdgeCDSS's Kokoro voice. It needs the portal's Python. | hand | H |
| `make_spellings.py` | Finds sound-alike spellings by letting the model hear synthetic clips of each name. | hand | H, T (via `teach_spellings.py`) |
| `teach_spellings.py` | The spelling step from the teach page, in one command. It reads your clips and contributors' results, keeps the safe spellings, refuses the rest with reasons, and with `--apply` writes `sounds_like.json` and `vosk_grammar.json`. | hand | H, T |
| `say_all.py` | Speaks every name Pocket says, numbered, so you can note the ones that sound wrong. | hand | H (on the board), T |
| `memprobe.py` | Measures the device's memory at each stage of start-up. | hand | H (`device/RADXA.md`, `docs/BOARDS.md`) |

## `tests/`: the checks

Each test file checks one ruling or feature; its first lines quote the ruling. **(PFC)** means the file runs on the retired PFC list as test data, not on the EMS list in use.

| File | What it checks | Made by | Used by |
|---|---|---|---|
| `test_acceptance.py` | The README's acceptance tests (A1, B1, C1, C2, E1, G1), typed. **(PFC)** | hand | T |
| `test_admin_time.py` | The administration time is said with the dose ("…over five minutes"). | hand | T |
| `test_autostart.py` | Power-up: the service, the install script, the speaker coming and going, the Wi-Fi script. | hand | T |
| `test_cautions.py` | Dose first; a caution is said only when it names a condition you stated, and the rest go to "why". **(PFC)** | hand | T |
| `test_confirm_step.py` | The confirm step: "why" and "repeat" at the read-back, two misses cancel, the 30-second expiry, the cancel words. Uses the confirm clips. | hand | T |
| `test_declared_strengths.py` | Your declared standard strengths give volumes; tablets stay milligrams only. | hand | T |
| `test_device.py` | The push-to-talk loop, with a stand-in mic, button and speaker. | hand | T |
| `test_ems_procedures.py` | RSI and failed airway on the EMS list: step text kept, each dose linked or held. | hand | T |
| `test_ems_set.py` | Every EMS entry signed, the record never claims an item review that did not happen, weight floors, silent entries, vials. | hand | T |
| `test_golden.py` | Every dose and volume matches EdgeCDSS's own code at 13 weights. **(PFC)** | hand | T |
| `test_hearing_ems.py` | The grammar is the EMS list: every signed drug can be said, and no retired-only word is in it. | hand | T |
| `test_hearing_fixes.py` | Route words ("in the vein" = IV), the "i dvt kilos" clips, confusable pairs. Uses your saved gate clips when `POCKET_OWNER_CLIPS` points at them; skips otherwise. | hand | T |
| `test_hearing_words.py` | The routes and commands hearing check is current and records each miss. | hand | T |
| `test_home_menu.py` | Home, drugs, procedures and help: never a dose. Uses the menu clips. | hand | T |
| `test_kit_vial_pinned.py` | An entry pinned to a vial says milligrams only. | hand | T |
| `test_one_list.py` | One drug list: no set switching, the PFC list refused. | hand | T |
| `test_one_mil_syringe.py` | Under 0.5 mL: the nearest 0.01 mL and "Use a one mil syringe."; no dilution. | hand | T |
| `test_pl_olmc_ignored.py` | Provider levels and OLMC are never said or used to hold a dose. | hand | T |
| `test_reachable.py` | Every signed entry can be reached by spoken words alone, and the dose logged is that entry's. **(PFC)** | hand | T |
| `test_readme.py` | The README's worked example is the engine's own output, word for word. | hand | T |
| `test_readme_header.py` | The README opens with the shared project header. | hand | T |
| `test_replay.py` | The replay phrases (`replay_corpus.json`) give exactly the expected answers. **(PFC)** | hand | T |
| `test_rounding_labels.py` | Volumes rounded by band; strengths said as the label reads ("five hundred per ten"). | hand | T |
| `test_rsi_adult_fixed_doses.py` | RSI 6 and 6b: ketamine 200 mg, rocuronium 100 mg, no succinylcholine, original text kept. | hand | T |
| `test_rsi_child_holds.py` | RSI holds whole for a child, by age, weight or "child". | hand | T |
| `test_rsi_fixes.py` | Fixes from your typed RSI run: "80kg", "repeat", "start over", the failed-airway question. | hand | T |
| `test_say_all.py` | The say-every-name tool and your spoken spellings. | hand | T |
| `test_spoken_routes.py` | Routes are said as words ("eye vee"), never as bare letters. | hand | T |
| `test_step_reader.py` | The RSI step reader on your signed steps. | hand | T |
| `test_teach_spellings.py` | The spelling step from the teach page. | hand | T |
| `test_test_bank.py` | The bench test list loads only with `POCKET_TEST=1` and says "Test set. Not for patient use." | hand | T |
| `test_vocabulary.py` | The word list comes from the drug list, and nothing outside it is recognised. **(PFC)** | hand | T |
| `test_written_form.py` | The written form on screen shows the route letters (IV); the spoken form says words. | hand | T |
| `test_file_map.py` | This map names every file in the repo and nothing that is not there. | hand | T |
| `replay_corpus.json` | 72 conversations with the exact answers expected, read by hand against the list and the rulings. | hand | T, H (`voice/bench.py`, `latency_typed.py`) |
| `latency_typed.py` | Times one typed phrase from text in to words out. It is not a test, despite the folder. **(PFC)** | hand | H |
| `fixtures/gen_edgecdss_golden.py` | Makes `edgecdss_golden.json` by running EdgeCDSS's own dose code. Needs an EdgeCDSS checkout. | hand | H |
| `fixtures/edgecdss_golden.json` | 1,404 doses and volumes computed by EdgeCDSS, for `test_golden.py`. **(PFC)** | generated: `fixtures/gen_edgecdss_golden.py` | T |
| `fixtures/clips/w1_iv_*.wav` (4 files) | Piper saying the web example where "IV" was once misheard ("i dvt kilos"). | generated: Piper (synthetic voice) | T (`test_hearing_fixes.py`) |
| `fixtures/clips/w1_miss_*.wav` (4 files) | Piper saying web example phrases that were once missed. | generated: Piper | T (`test_hearing_fixes.py`, through the `w1_*` pattern) |
| `fixtures/clips/confirm/kokoro__*.wav` (30 files) | Confirm, cancel and similar words in three Kokoro voices. | generated: `voice/tools/synth_kokoro.py` | T (`test_confirm_step.py`) |
| `fixtures/clips/confirm/piper__*.wav` (47 files) | The same words in Piper's voice (20 takes of "no"). | generated: Piper | T (`test_confirm_step.py`) |
| `fixtures/clips/menu/kokoro__*.wav` (21 files) | Home, drugs, procedures, help and similar words in three Kokoro voices. | generated: `voice/tools/synth_kokoro.py` | T (`test_home_menu.py`) |
| `fixtures/clips/menu/piper__*.wav` (7 files) | The same words in Piper's voice. | generated: Piper | T (`test_home_menu.py`) |

**Not in the repo, but needed:**
- The hearing model (`models/vosk-model-small-en-us-0.15`) and the Piper voice, downloaded by `install.sh` and checked by fingerprint.
- Your recorded clips (`bench-out/…`, `~/pocket-web/owner-clips`). These stay out of the repo by rule; 4 tests (the hearing checks on your voice) skip without them.
- The formulary, the signing packets and `sign_bulk.py`, in `~/formulary`.

---

## How a spoken request travels through the files

Take "ketamine for RSI, IV, eighty kilos" on the board.

1. **Power-up.** `device/pocket.service` starts `voice/autostart.py`. It loads `bank/ems/*` through `engine/bank.py`, which checks the signature fingerprints in `manifest.json` or refuses. It loads `bank/ems/procedures.json` through `engine/procedures.py`, builds the word list (`grammar/vocabulary.py`), loads the hearing model with `grammar/vosk_grammar.json`, and loads Piper. It says the start-up line.
2. **Press and speak.** `voice/device.py` waits for the button (`voice/listen.py`) and plays the beep. `voice/listen.py` sends the microphone audio between press and release.
3. **Hearing.** `voice/hear.py` runs two Vosk decoders limited to the words in `grammar/vosk_grammar.json`, one with the sound-alike spellings (`grammar/sounds_like.json`) and one without. `voice/spoken.py` maps spellings and spelled letters back to names. The result is plain words, such as "ketamine for r s i i v eighty kilos".
4. **Reading.** `grammar/parser.py` reads the words into slots over the word list: drug ketamine, indication RSI, route IV, weight 80 kg. One unknown word and the phrase is refused. A pair from `grammar/confusable.json` asks "X or Y?" first.
5. **The questions.** `engine/session.py` finds the signed entries in `bank.json` that match. It asks for anything missing, holds anything not signed, and reads back: "Ketamine, RSI, IV, eighty kilos. Confirm?"
6. **Confirm.** On "confirm", `engine/contracts.py` works out the dose from the signed entry (here a fixed 200 mg). `engine/vials.py` gives the volume only from a signed vial in `kit.json` (2 mL of 100 mg/mL). `engine/words.py` writes the numbers as words.
7. **Speaking.** `voice/speak.py` has Piper say "Ketamine two hundred milligrams. Two mils of one hundred per mil." Only cautions for a condition you stated follow; the rest wait for "why". The dose is logged.

**On the web**, the portal (`pi-cloud-cdss/server/pocket_web.py`) replaces steps 1–3 and 7. It takes the browser's audio, uses `voice/hear.py` and the same grammar and bank from the pinned checkout, runs the same `engine/session.py`, and speaks with its own Piper. Steps 4–6 are the same files.

---

## Dead, duplicated or confusingly named

**Dead**
1. `device/setup_voice.sh` and `device/memory.sh` are for the Raspberry Pi Zero 2 W, which was dropped. Only the board notes mention them.
2. `memory.sh` says "A later pocket.service sets Slice=pocket.slice"; `pocket.service` does not.
3. Leftovers of the two-list era in live code: `engine/session.py` still has the PFC/EMS set names, the "P F C" menu letters and a PFC-only ketamine dilution rule. `engine/bank.py` still has the whole bench test-list switch (`POCKET_TEST`), but no test list ships in the repo; the tests build one.

**Duplicated**
4. `bank/retired/pfc/procedures.json` and `bank/ems/procedures.json` both carry the RSI steps. The EMS file names the retired one as its source (`steps_from`), so the retired folder is part of the signed steps' paper trail.
5. `device/setup_voice.sh` and `device/install.sh` both install Vosk and the model (Pi Zero and Radxa).
6. Small volumes are tested in both `test_one_mil_syringe.py` and `test_rounding_labels.py`. The README is tested by two files.

**Confusingly named or placed**
7. "Grammar" means three things:
   - `grammar/`: the word list and phrase reader;
   - `voice/grammar.py`: the program that builds the hearing list;
   - `grammar/vosk_grammar.json`: that program's output, which sits in the other folder and is also rewritten by `teach_spellings.py`.
8. "Device" means two things: `device/` (setting up the board) and `voice/device.py` (the push-to-talk loop).
9. Tests live in three folders (`engine/tests`, `tests`, `voice/tests`). Two files in `tests/` are not tests: `latency_typed.py` (a timer) and `fixtures/gen_edgecdss_golden.py` (a generator).
10. Hearing results (`voice/dryrun_*.json`) sit beside the hearing code, while the tools that make them are in `voice/tools/`.
11. Board notes are split between `device/RADXA.md` and `docs/BOARDS.md`. The roadmap is at the top level, the work order in `docs/`.
12. `bank/ems/manifest.json` says it was `converted_by` "EdgeCDSS export_pocket_bank.py (EMS-TEST, 2026-11-15)", although the list is the signed EMS set, not the test list.
13. `grammar/sounds_like.json` mixes the live spellings with the history of dropped ones and their notes (fourteen top-level sections).
14. `engine/session.py` is 1,085 lines. It holds the questions, the read-back, the menus, the cautions, the RSI step reader, the child hold and the PL/OLMC filter.

**Worth knowing before a restructure**
15. Several core checks run on the **retired PFC list**, not the EMS list in use:
    - every signed entry reachable by voice (`test_reachable.py`);
    - every dose matching EdgeCDSS (`test_golden.py`);
    - the replay phrases (`test_replay.py`);
    - the acceptance tests;
    - the cautions;
    - the word-list tests;
    - the ported dose-arithmetic tests.

    The EMS list has its own checks (`test_ems_set.py`, `test_hearing_ems.py` and the ruling tests), but no "every entry reachable by voice" or "matches EdgeCDSS" check of its own.
16. Hidden links to other repos:
    - The portal imports a private name, `_say_term`, from `grammar/vocabulary.py`, and reads `voice/dryrun_*.json` by path.
    - `voice/tools/synth_kokoro.py` and the documented test command need the portal's Python (`~/pi-cloud-cdss/.venv`).
    - Moving or renaming any of these breaks the web page at its next pin.
17. The 4 hearing tests on your own voice skip unless `POCKET_OWNER_CLIPS` points at your saved clips, so a run without them still looks green (3,475 passed, 4 skipped; with them, 3,479 passed). That is how #36 broke three of them without anyone noticing (fixed in #40).
