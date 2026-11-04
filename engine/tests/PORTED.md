# What was ported from EdgeCDSS, and what was not

Source: `server/` at the commit in `bank/manifest.json`. The README says "same tests"; this is how far that goes.

**Code.** `classify_units`, `_limit_mg`, `resolve_dose`, `range_text`, `age_exclusion`, the age band, the population preference, `draw_precision`, `drawable`, `volume_ml` and `resolve_dose_volume` keep their logic. `number_words` is `spoken.py`'s. `tests/test_golden.py` compares them with EdgeCDSS's own output for all 108 entries at 13 weights (1,404 rows, `tests/fixtures/gen_edgecdss_golden.py`).

**The pre-gate is rewritten, not copied.** `pre_gate()` reads free text and history with regular expressions. Pocket has slots from a closed grammar, so `engine/session.py` keeps its questions and their order, not its code.

| EdgeCDSS tests | Functions there | Here |
|---|---|---|
| `test_dose_units.py` | 21 | Units, refusals, rate, cap: same cases and values (`test_contracts_ported.py`). Drawable table in `test_vials_ported.py`. |
| `test_minimum_dose.py` | 18 | The floor's arithmetic: same cases. Not the signing checks (EdgeCDSS's gate, at export). |
| `test_drug_contracts.py` | 117 | Age floor, band, population, `range_text`. The rest pin the contract file's history, rulings, lints and the RSI cards. |
| `test_drug_concentrations.py` | 62 | Draw precision, resolve, volume. Not the free-text audit, the signing tool, the change log or the vial question (no model output to audit; no vial question in Pocket's grammar). |
| `test_k1_*`, `test_k3_*` | 48 | The arithmetic rulings. Not the card, brief and spoken-brief wording. |
| `test_ask_which_indication.py` | 17 | The live case and the rules, as session phrases (`test_pregate_ported.py`), not verbatim. |
| `test_a39_*`, `test_weight_confidence.py`, `test_fixed_dose_needs_adult.py` | | The behaviour, as session phrases, not verbatim. |

**Not ported, because Pocket's grammar cannot state what they read:** the patient-condition gates: succinylcholine under a P5 condition (A12), depressed-GCS oral route (A4), contraindicated procedures (A6), vitals cautions, pain severity. The RSI, seizure and DCR cards. Everything that checks a model's text (Pocket has no model).
