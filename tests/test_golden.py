"""The port against the code it came from: every entry at 13 weights, computed by
EdgeCDSS's own resolve_dose and resolve_dose_volume (fixtures/gen_edgecdss_golden.py)."""
import json
import pathlib

import pytest

from engine.bank import load_bank
from engine.contracts import range_text, resolve_dose
from engine.vials import dose_volume

ROOT = pathlib.Path(__file__).resolve().parents[1]
GOLDEN = json.loads((ROOT / "tests" / "fixtures" / "edgecdss_golden.json").read_text())
BANK = load_bank(ROOT / "bank")
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
    v = dose_volume(BANK.kit, e, round(r["dose_mg"], 4))
    assert v["volume_ml"] == row["volume_ml"]
    assert v["concentration_mg_ml"] == row["concentration_mg_ml"]
    assert v["diluted"] == row["diluted"]
    assert bool(v["refusal"]) == row["refused"]
