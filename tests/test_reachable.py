"""Every signed entry, by spoken words alone. Each one is requested through the
grammar with the questions answered; the dose logged must be that entry's and no
other."""
import pathlib

import pytest

from engine.bank import load_bank
from engine.contracts import age_band, resolve_dose
from engine.session import boot
from grammar.vocabulary import build, label_tokens

ROOT = pathlib.Path(__file__).resolve().parents[1]
BANK = load_bank(ROOT / "bank")
VOCAB = build(BANK)


def key(e):
    return f"{e['drug']} | {e['indication']} | {e['route']} | {e['population']}"


def request(e):
    term = VOCAB.named(e["drug"])[0]
    cls = VOCAB.class_terms_for(e["indication_class"])[0]
    peds_only = e["population"] == "peds"
    patient = "child twenty kilos" if peds_only else "eighty kilos"
    band = age_band(e)
    if band:
        patient = f"child {'three' if band[1] <= 5 else 'six'} years twenty kilos"
    return f"{term} for {cls} {e['route'].lower()} {patient}"


def walk(e):
    """The phrases a medic would say for this entry, or None if the flow stalls."""
    s = boot(ROOT / "bank")
    turn = s.handle(request(e))
    for _ in range(4):
        if turn.kind == "readback":
            dose = s.handle("confirm")
            return dose if dose.kind == "dose" else None
        if turn.kind != "ask" or not turn.say.startswith("Which one"):
            return None
        turn = s.handle(" ".join(sorted(label_tokens(e["indication"]) & VOCAB.label_words)))
    return None


@pytest.mark.parametrize("e", BANK.entries, ids=key)
def test_every_signed_entry_is_reachable_and_is_that_entry(e):
    dose = walk(e)
    assert dose is not None, request(e)
    r = dose.data["record"]
    assert (r["drug"], r["indication"]) == (e["drug"], e["indication"])
    want = resolve_dose(e, 20.0 if e["population"] == "peds" else 80.0)
    if want["dose_mg"] is not None:
        assert r["dose"] == f"{want['display_value']:g} {want['display_units']}"
