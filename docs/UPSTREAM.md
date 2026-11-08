# What Pocket needs from EdgeCDSS

Pocket signs nothing. Everything below is a change in EdgeCDSS
(`AI-in-Austere-Medicine-Project/pi-cloud-cdss`), signed there by the owner, then
re-exported here with `server/tools/export_pocket_bank.py`. Each item is its own
EdgeCDSS PR with its own failing test.

## Needed

### 1. Exporter PR merged: pi-cloud-cdss #199

`bank/manifest.json` names EdgeCDSS commit `0b0af9b` (bank version
`1.4.0+2026-11-04.0b0af9b`). That commit is on the open branch `pocket-bank-export`, not on
main. Until #199 merges, the bank here comes from a commit that is not on EdgeCDSS
main. Once it merges, re-export from main and commit the new `bank/` here. The
tests check the manifest hashes, so the bank and its manifest can't drift apart.

### 2. Split ketamine's blood-pressure contraindication

`server/drug_contracts.json`, `drugs[0].dose_entries[1].contraindications[1]`
(ketamine, prolonged sedation infusion, IV, adult):

> Conditions that cannot tolerate sustained increases in blood pressure: non-traumatic
> intracerebral hemorrhage, hypertension associated with acute coronary syndrome; NOT
> contraindicated in TBI (SMOG CY24 p.127)

Pocket treats a line that qualifies itself ("not contraindicated", "unless", "except",
"relative", "none in") as spoken text, not as a hold. This line carries "NOT
contraindicated in TBI", so its intracerebral haemorrhage clause never holds. Proposed
split, for the owner to sign against SMOG CY24 p.127:

- `Non-traumatic intracerebral hemorrhage (SMOG CY24 p.127)`: a gate ("intracranial bleed").
- `Hypertension associated with acute coronary syndrome (SMOG CY24 p.127)`: a gate.
- `Not contraindicated in TBI (SMOG CY24 p.127)`: spoken, not a gate.

There is a related question for the same signing. The peds infusion entry
(`dose_entries[2]`) quotes the same SMOG passage but doesn't list the line as a
contraindication. Should it?

Test on the Pocket side once re-exported: the adult ketamine infusion entry holds on
"intracranial bleed".

## Findings recorded in EdgeCDSS, not yet fixed there

- **"estimated" doses in EdgeCDSS.** "ketamine for agitation estimated 80 kg IV" counts as
  a confirmed weight and doses. Pocket asks for the weight instead (F-1). This is
  recorded in EdgeCDSS `docs/REFERENCE.md` section 9 by #199 and needs its own PR.
- **K3 under 0.05 mL at the vial.** A child under 12.5 kg on 0.2 mg/kg IV ketamine gets mg
  and the dilution recipe, but no volume. It fails safe. Owner ruling: a K3 question for
  EdgeCDSS; Pocket leaves it as it is.

## Would let Pocket say more (not blocking)

Each of these is a gap described in the Phase 1 PR, under "What the engine could not
express".

- **Structured repeat and cumulative limits.** `repeat` is free text on 43 entries and
  absent on 65; `max_cumulative` is on 11 and untracked.
- **Signed vials for more drugs.** Only 6 drugs have one, so 76 of 108 entries give mg
  only.
- **Quotes, and which field a citation backs.** 69 entries have no quote, and 63
  citations don't say which field they support.
- **Named signers.** Every entry's signer is the role `AI-AIM`.
- **Indication cue words as data.** These are regexes in EdgeCDSS today, so the grammar
  can't use them.
- **Speakable names.** `d50`, `3% saline` and similar names have no form the grammar can
  say.
- **Signed procedure holds (P5) in the export.** Pocket's succinylcholine hold and its
  rocuronium alternative come from the dose entries' own contraindications and labels.
  Exporting the signed P5 row would let the hold cite ID40 p.3 directly.
