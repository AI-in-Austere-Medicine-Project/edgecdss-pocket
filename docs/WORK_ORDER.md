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
- 2026-11-21: Pocket starts by itself at power-up (`pocket.service`, `voice/autostart.py`, `device/install.sh`): the speaker retried until it connects, "No microphone found.", no network; power-cut settings (no swap on the card, journal in RAM, noatime, no background apt; dose log and its directory fsynced).
- 2026-11-22: the EMS set, every formulary entry (`bank/ems/`), signed by the owner (Andrew Azelton): 206 of 206. 178 can be said; 28 are signed but silent (mEq, topical, SL, several weight bands): Pocket says the drug "is signed, but Pocket cannot say its dose yet". Every record says how it was signed: "individually read by owner" (44: the 22 ruled on 2026-11-12, signing batch 1, and the four rule-3 entries) or "bulk-signed by owner without item review" (162). The owner's bulk-signature rules: 1 the numbers as read from the page; 2 a weight table against the per-kg dose: the per-kg dose with its stated maximum, except that a band the table gives no dose ("None", "No IV dose") is a weight floor: Pocket holds below it, "No signed dose at this weight" (14 entries carry `min_weight`, 3 of them from a row that states the limit in words); 3 a card that contradicts itself where no rule picks the number: not signed until the owner rules (four infusion times, ruled: the row's time, the table's disagreement noted); 4 a missing or contradicting strength: milligrams only, no volume, until declared (declared: adenosine 12 mg in 4 mL); 5 naloxone signed with its DRAFT watermark noted; 6 entries Pocket cannot say: signed, silent; 7 the research-prototype notice on everything. The signing tool and the packets stay with the formulary, outside the repo. The device still runs the PFC set; no hearing work for the new drugs yet.
- 2026-11-22: the administration time is said with the dose: "Tranexamic acid two grams. Twenty mils of one hundred. Over ten minutes." From the first caution Pocket serves that states "over N minutes / seconds / hours" (alternatives joined by "or"), and for an EMS entry from its printed row's route cell; a PFC quote is not used (it can time another route). 13 PFC entries say a time; three replay answers changed accordingly.
