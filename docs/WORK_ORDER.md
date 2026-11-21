# EdgeCDSS Pocket work order

## Rules (owner, 2026-11-20)

1. Only signed entries speak.
2. Every change has a test. The full Pocket test suite must stay fast.
3. One PR per feature. The owner merges.
4. Ask the owner only to sign an entry or to judge something by ear on the device. Decide everything else, and tell the owner after.

Pocket has no model, so it has no replays, no validator and no row-by-row rulings.

"Fast": the full suite (`python -m pytest -q`) took 105 s on 2026-11-20 (3,045 passed). A PR that makes it slower says why in its description.

The order of the sections is in [ROADMAP.md](../ROADMAP.md). Device notes are in [device/RADXA.md](../device/RADXA.md).

## Log

- 2026-11-20: work order started with the rules above.
- 2026-11-20: RSI step reader on the steps the owner signed from the 2026-11-20 packet (`bank/procedures.json`). Next batch, not now: etomidate, vecuronium, and ketamine post-intubation re-sourced to SMOG p.12.
- 2026-11-21: fixes from the owner's typed RSI run on the Radxa: typed numbers, "repeat" re-reads the step, "start over", failed airway asks "Can you mask ventilate?", short start-up line.
- 2026-11-21: the voice session on the device (`voice/device.py`): push-to-talk, beep, the answer spoken through Piper, stopped by a press; drugs and procedure steps.
- 2026-11-21: home menu, help and command lists: start-up "Pocket ready.", "home", "drugs", "procedures", "help", "what can I say" (per state); typed mode cut off by Enter. Three spellings holding a new one-word command dropped (one signed: ceftriaxone's "zev drugs own"); the drug dry run is unchanged (177 of 183, none as another drug).
- 2026-11-21: the spelling step from the teach page, one repeatable command (`voice/tools/teach_spellings.py`): 5 spellings added, 61 refused; the owner's gate 28 of 30 before and after, none as another drug; the dry run unchanged (177 of 183, 0). `voice/tools/say_all.py`: every name Pocket says, numbered, for the owner's ear; spoken spellings go in `engine/words.SAY_AS`.
