"""Hearing every drug name in both sets (owner, 2026-11-22): "add every EMS drug name and
its common names to the grammar, with the collision checks."

One vocabulary hears both sets' names; a session doses from the set it has loaded. A drug
signed in the other set is named, with the set to load: never "Not recognised.", never a
dose from the other set. The grammar is built from both sets.
"""
import json
import pathlib

from engine.bank import SET_DIRS, load_bank, load_sets, merge_banks
from engine.session import IN_OTHER_SET, boot_sets
from grammar.vocabulary import MEDIC_NAMES, build

ROOT = pathlib.Path(__file__).resolve().parents[1]
GRAMMAR = json.loads((ROOT / "grammar" / "vosk_grammar.json").read_text())
UNION = merge_banks(load_sets().values())
VOCAB = build(UNION)
EMS = load_bank(SET_DIRS["EMS"], test=False)
PFC = load_bank(SET_DIRS["PFC"], test=False)


def test_the_union_holds_every_signed_drug_of_both_sets_and_doses_none():
    assert VOCAB.signed == PFC.signed_drugs | EMS.signed_drugs | EMS.silent_drugs
    assert len(VOCAB.signed) == 45 and UNION.kit == {}


def test_the_grammar_is_built_from_both_sets_and_every_signed_drug_can_be_said():
    assert GRAMMAR["bank_version"] == f"{PFC.version}+{EMS.version}"
    assert GRAMMAR["signed_drugs_not_sayable"] == []


def test_every_ems_common_name_names_its_drug():
    for said, generic in MEDIC_NAMES.items():
        assert generic in VOCAB.signed, said
        assert generic in VOCAB.drug_terms.get(said, ()), said
    assert VOCAB.drug_terms["benadryl"] == ("diphenhydramine",)
    assert VOCAB.drug_terms["zofran"] == ("ondansetron",)


def test_a_drug_in_the_other_set_is_named_with_the_set_to_load():
    s = boot_sets(SET_DIRS, "PFC")
    t = s.handle("benadryl for allergic reaction im adult")
    assert t.kind == "hold" and s.bank.kit_id.startswith("austere")
    assert t.written == IN_OTHER_SET.format(name="diphenhydramine", here="PFC set", there="EMS set")
    assert t.say == ("No signed dose of diphenhydramine in the P F C set. "
                     "It is in the E M S set; say E M S set to load it.")
    s.handle("ems set")
    assert s.handle("benadryl for allergic reaction im adult").kind == "readback"
    assert s.handle("artesunate").written.startswith("No signed dose of artesunate in the EMS set. It is in the PFC set")


def test_a_signed_but_silent_drug_is_heard_and_says_it_cannot_say_its_dose():
    s = boot_sets(SET_DIRS, "EMS")
    assert s.handle("bicarb").written == "Sodium bicarbonate is signed, but Pocket cannot say its dose yet."


def test_the_dry_run_covers_both_sets_and_hears_no_drug_as_another():
    d = json.loads((ROOT / "voice" / "dryrun_drugs.json").read_text())
    assert {r["drug"] for r in d["rows"]} == VOCAB.signed
    assert (d["names"], d["clips"]) == (112, 336)
    assert d["heard"] >= 320 and d["heard_as_another_drug"] == 0


def test_an_indication_longer_than_a_drug_name_is_read_as_the_indication():
    """The EMS set brings "calcium channel" (blocker overdose) as an indication; "calcium" is
    a drug name. The longer reading wins, so the indication can be asked for."""
    from grammar.parser import parse
    p = parse("calcium chloride for calcium channel blocker overdose", VOCAB)
    assert [d.generics for d in p.drugs] == [("calcium chloride",)] and p.classes == [VOCAB.class_terms["calcium channel"]]
    s = boot_sets(SET_DIRS, "EMS")
    assert s.handle("calcium chloride for calcium channel blocker overdose iv twenty kilos").kind == "readback"
