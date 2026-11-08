"""README acceptance tests A1, B1, C1, C2, E1, G1, typed. They become spoken
tests in phase 2."""
import json
import pathlib
import shutil

import pytest

from engine.session import boot

BANK = pathlib.Path(__file__).resolve().parents[1] / "bank"


@pytest.fixture
def s():
    return boot(BANK)


def play(session, *phrases):
    return [session.handle(p) for p in phrases]


# ── A1 ─────────────────────────────────────────────────────────────────────

def test_a1_new_patient_clears_weight_and_the_next_dose_asks_for_it(s):
    *_, dose = play(s, "ketamine for agitation iv eighty kilos", "confirm")
    assert dose.kind == "dose"
    cleared = s.handle("new patient")
    assert cleared.say == "New patient. Weight and age cleared."
    next_turn = s.handle("ketamine for agitation iv")
    assert next_turn.say == "Weight?"
    assert "eighty" not in next_turn.text


def test_a1_new_patient_never_reuses_a_child_either(s):
    play(s, "child morphine for pain iv twenty kilos", "confirm", "new patient")
    # No weight and no "child" left: an adult's entry can only come from a new weight.
    assert s.handle("morphine for pain iv").say == "Weight?"
    readback = s.handle("eighty kilos")
    assert readback.say == "Morphine, pain, IV, eighty kilos. Confirm?"


def test_a1_new_patient_in_the_read_back_drops_the_pending_dose(s):
    play(s, "ketamine for agitation iv eighty kilos", "new patient")
    assert s.handle("confirm").say == "Nothing to confirm."


def test_a1_new_patient_and_a_request_in_one_phrase_asks_for_weight(s):
    play(s, "ketamine for agitation iv eighty kilos", "confirm")
    assert s.handle("new patient ketamine for agitation iv").say.endswith("Weight?")


# ── B1 ─────────────────────────────────────────────────────────────────────

def _b1(session, spoken):
    first = session.handle(f"ketamine {spoken}")
    session.handle("eighty kilos")
    session.handle("agitation")
    readback = session.handle("iv")
    dose = session.handle("confirm")
    return first, readback, dose


def test_b1_the_spoken_amount_is_read_back_as_spoken(s):
    first, readback, _ = _b1(s, "five hundred milligrams")
    assert first.say == "Heard ketamine five hundred milligrams. Weight?"
    assert readback.say == ("Ketamine, agitation, IV, eighty kilos. "
                            "You said five hundred milligrams. Confirm?")


def test_b1_the_engines_own_dose_is_given(s):
    _, _, dose = _b1(s, "five hundred milligrams")
    assert dose.say == "Ketamine one hundred and sixty milligrams. Three point two mils of fifty."
    assert "five hundred" not in dose.text


@pytest.mark.parametrize("spoken", ["one milligram", "five hundred milligrams",
                                    "nine thousand milligrams", "two grams",
                                    "zero point five micrograms"])
def test_b1_the_spoken_number_is_never_computed_on(spoken):
    """Same dose, same volume, whatever was said."""
    _, _, dose = _b1(boot(BANK), spoken)
    assert dose.say == "Ketamine one hundred and sixty milligrams. Three point two mils of fifty."


def test_b1_the_parser_keeps_the_amount_as_words_only(s):
    parsed = s.parse("ketamine five hundred milligrams")
    assert parsed.stated == ["five hundred milligrams"]
    assert all(isinstance(x, str) for x in parsed.stated)
    assert parsed.weight is None
    assert parsed.age is None


@pytest.mark.parametrize("vial", ["fifty milligrams per mil", "fifty mg per ml",
                                  "five hundred milligrams in ten mils"])
def test_b1_a_stated_vial_that_is_the_signed_vial_gives_the_volume(s, vial):
    # Owner ruling 2026-11-08. The words are compared with the signed vial's own
    # words; the volume is the kit's, never worked out from what was said.
    play(s, f"ketamine for agitation iv eighty kilos {vial}")
    dose = s.handle("confirm")
    assert dose.say == "Ketamine one hundred and sixty milligrams. Three point two mils of fifty."
    assert dose.data["record"]["volume_ml"] == 3.2


@pytest.mark.parametrize("vial", ["one hundred milligrams per mil", "five hundred milligrams in five mils",
                                  "ten mils", "fifty micrograms per mil", "five milligrams per mil"])
def test_b1_a_stated_vial_that_is_not_the_signed_vial_is_not_used(s, vial):
    play(s, f"ketamine for agitation iv eighty kilos {vial}")
    dose = s.handle("confirm")
    assert dose.say == "Ketamine one hundred and sixty milligrams. Stated vial not used, no volume."
    assert dose.data["record"]["volume_ml"] is None


def test_b1_one_stated_vial_that_is_not_signed_withholds_the_volume(s):
    play(s, "ketamine for agitation iv eighty kilos fifty milligrams per mil one hundred milligrams per mil")
    assert s.handle("confirm").say.endswith("Stated vial not used, no volume.")


def test_b1_another_drugs_vial_is_not_this_drugs(s):
    # Rocuronium's signed vial is 10 mg/mL; said for ketamine it is not ketamine's.
    play(s, "ketamine for agitation iv eighty kilos ten milligrams per mil")
    assert s.handle("confirm").say.endswith("Stated vial not used, no volume.")


# ── C1 ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("phrase", ["keto", "keto for pain", "keto for pain eighty kilos iv",
                                    "ket", "keta"])
def test_c1_a_name_close_to_two_drugs_asks(s, phrase):
    turn = s.handle(phrase)
    assert turn.kind == "ask"
    assert turn.say == "Ketamine or ketorolac?"


def test_c1_there_is_no_auto_resolution_on_repeat(s):
    s.handle("keto for pain eighty kilos iv")
    assert s.handle("keto").say == "Ketamine or ketorolac?"
    assert s.handle("confirm").say == "Nothing to confirm."


def test_c1_the_answer_keeps_what_was_already_said(s):
    s.handle("keto for agitation eighty kilos iv")
    assert s.handle("ketamine").say == "Ketamine, agitation, IV, eighty kilos. Confirm?"


def test_c1_answering_ketorolac_holds(s):
    s.handle("keto for pain eighty kilos iv")
    assert s.handle("ketorolac").say == "No signed dose for ketorolac."


# ── C2 ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("phrase,heard", [
    ("magnesium", "magnesium"), ("magnesium for seizure eighty kilos iv", "magnesium"),
    ("ketorolac for pain", "ketorolac"), ("toradol", "toradol"), ("amiodarone", "amiodarone"),
])
def test_c2_an_unsigned_drug_speaks_the_hold_and_nothing_else(s, phrase, heard):
    turn = s.handle(phrase)
    assert turn.kind == "hold"
    assert turn.text == f"No signed dose for {heard}."


def test_c2_nothing_follows_the_hold(s):
    s.handle("magnesium")
    assert s.handle("confirm").say == "Nothing to confirm."
    assert s.handle("why").say == "No dose to explain."


# ── E1 ─────────────────────────────────────────────────────────────────────

def _tampered(tmp_path, edit, rehash=True):
    import hashlib
    d = tmp_path / "bank"
    shutil.copytree(BANK, d)
    bank = json.loads((d / "bank.json").read_text())
    edit(bank)
    (d / "bank.json").write_text(json.dumps(bank))
    if rehash:
        man = json.loads((d / "manifest.json").read_text())
        man["sha256"]["bank.json"] = hashlib.sha256((d / "bank.json").read_bytes()).hexdigest()
        (d / "manifest.json").write_text(json.dumps(man))
    return d


def _unsign(bank):
    bank["entries"][0]["signoff"] = False


def _pending_signer(bank):
    bank["entries"][0]["signer"] = "PENDING_CLINICAL_SIGNOFF"


def _sentinel(bank):
    bank["entries"][0]["cautions"][0]["text"] = "NEEDS_MANUAL_ENTRY"


def _example(bank):
    bank["bank_version"] = "EXAMPLE-1"


@pytest.mark.parametrize("edit", [_unsign, _pending_signer, _sentinel, _example])
def test_e1_an_unsigned_or_example_bank_is_announced_and_refuses_all_doses(tmp_path, edit):
    s = boot(_tampered(tmp_path, edit))
    assert s.announce.kind == "refused"
    assert s.announce.say.startswith("Bank refused")
    for phrase in ("ketamine for agitation iv eighty kilos", "confirm", "why",
                   "new patient", "magnesium"):
        turn = s.handle(phrase)
        assert turn.kind == "refused"
        assert "milligrams" not in turn.text


def test_e1_a_bank_whose_hash_does_not_match_is_refused(tmp_path):
    s = boot(_tampered(tmp_path, lambda b: None, rehash=False))
    # json re-serialised: the bytes moved, so the manifest no longer describes them.
    assert s.announce.kind == "refused"


def test_e1_a_missing_bank_is_refused(tmp_path):
    assert boot(tmp_path / "nothing").announce.kind == "refused"


# ── G1 ─────────────────────────────────────────────────────────────────────

ENTRIES = json.loads((BANK / "bank.json").read_text())["entries"]


def test_g1_boot_announces_bank_version_and_hash(s):
    man = json.loads((BANK / "manifest.json").read_text())
    assert s.announce.kind == "boot"
    assert s.announce.data["bank_version"] == man["bank_version"]
    assert s.announce.data["hash"] == man["sha256"]["bank.json"][:8]
    assert s.announce.say.startswith("Bank version ")
    assert " hash " in s.announce.say.lower()


def test_g1_why_speaks_the_source_of_the_dose_just_given(s):
    play(s, "ketamine for agitation iv eighty kilos", "confirm")
    entry = next(e for e in ENTRIES if e["drug"] == "ketamine" and e["route"] == "IV"
                 and e["population"] == "adult" and e["indication_class"] == "agitation")
    why = s.handle("why")
    assert why.kind == "why"
    assert entry["source"] in why.say
    assert entry["signer"] in why.say
    assert entry["date"] in why.say


def test_g1_why_works_at_the_read_back_and_does_not_lose_it(s):
    s.handle("ketamine for agitation iv eighty kilos")
    assert s.handle("why").kind == "why"
    assert s.handle("confirm").kind == "dose"


@pytest.mark.parametrize("i", range(len(ENTRIES)))
def test_g1_every_entry_can_speak_its_source(i):
    """Through the engine's own `why`, for each of the signed entries."""
    from engine.session import why_text
    e = ENTRIES[i]
    text = why_text(e)
    assert e["source"] in text
    assert e["signer"] in text and e["date"] in text
    if e["quote"]:
        assert e["quote"] in text
    if e["page"] is not None:
        assert "Page" in text


# ── D1 is not in phase 1's list, but the corpus holds its invariant ─────────

def test_only_confirm_proceeds(s):
    s.handle("ketamine for agitation iv eighty kilos")
    for phrase in ("yes", "ok", "go", "give it", "repeat", "why", "eighty kilos"):
        assert s.handle(phrase).kind != "dose", phrase
    assert s.handle("confirm").kind == "dose"
