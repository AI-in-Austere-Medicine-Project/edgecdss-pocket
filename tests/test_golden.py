"""The port against the code it came from: every entry at 13 weights, computed by
EdgeCDSS's own resolve_dose and resolve_dose_volume (fixtures/gen_edgecdss_golden.py)."""
import json
import pathlib

import pytest

from engine.bank import PFC_RETIRED, load_bank
from engine.contracts import range_text, resolve_dose
from engine.contracts import signed_max_mg
from engine.vials import dose_volume, round_volume

ROOT = pathlib.Path(__file__).resolve().parents[1]
GOLDEN = json.loads((ROOT / "tests" / "fixtures" / "edgecdss_golden.json").read_text())
BANK = load_bank(PFC_RETIRED, retired_ok=True)
ENTRY = {(e["drug"], e["indication"], e["route"], e["population"]): e for e in BANK.entries}


def test_every_entry_is_covered():
    assert {tuple(r["key"]) for r in GOLDEN} == set(ENTRY)
    assert len(GOLDEN) == 13 * len(ENTRY)


@pytest.mark.parametrize("row", GOLDEN, ids=lambda r: f"{r['key'][0]}-{r['key'][2]}-{r['weight']}")
def test_same_dose_and_volume_as_edgecdss(row):
    e = ENTRY[tuple(row["key"])]
    r = resolve_dose(e, row["weight"])
    assert r["kind"] == row["kind"]
    assert r["dose_mg"] == row["dose_mg"]
    assert (r["display_value"], r["display_units"]) == (row["display_value"], row["display_units"])
    assert r["floor_applied"] == row["floor_applied"]
    assert range_text(e) == row["range_text"]
    if row["dose_mg"] is None:
        return
    v = dose_volume(BANK.kit, e, round(r["dose_mg"], 4), signed_max_mg(e, row["weight"]))
    if row["volume_ml"] is None and not row["diluted"]:
        assert v["volume_ml"] is None and bool(v["refusal"]) == row["refused"]
        return
    # The dose is EdgeCDSS's to the milligram (above). The volume is Pocket's own rule
    # (owner, 2026-11-22: no dilution; rounded by band; never above the signed maximum),
    # from the same vial.
    vial = BANK.kit[e["drug"]][0]["concentration_mg_ml"]
    true = round(r["dose_mg"], 4) / vial
    want = round_volume(true, vial, signed_max_mg(e, row["weight"])) if true >= 0.05 else None
    assert (v["volume_ml"], v["concentration_mg_ml"] if want else None, v["diluted"]) == (want, vial if want else None, False)
