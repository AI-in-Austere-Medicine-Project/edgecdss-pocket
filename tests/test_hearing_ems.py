"""Hearing the one drug list, the EMS set (owner decision, 2026-11-23): "rebuild the grammar
from the EMS list only." It replaces hearing both sets (2026-11-22).

The grammar is built from the EMS set alone: every signed EMS drug can be said, and no word
that only a retired PFC drug used is in it, so a retired name cannot pull a sound to itself.
"""
import json
import pathlib

from engine.bank import BANK_DIR, PFC_RETIRED, load_bank
from engine.session import boot
from grammar.vocabulary import MEDIC_NAMES, build

ROOT = pathlib.Path(__file__).resolve().parents[1]
GRAMMAR = json.loads((ROOT / "grammar" / "vosk_grammar.json").read_text())
EMS = load_bank(BANK_DIR, test=False)
VOCAB = build(EMS)


def test_the_vocabulary_is_the_ems_set():
    assert VOCAB.signed == EMS.signed_drugs | EMS.silent_drugs
    assert len(VOCAB.signed) == 32


def test_the_grammar_is_built_from_the_ems_set_and_every_signed_drug_can_be_said():
    assert (GRAMMAR["bank_version"], GRAMMAR["bank_hash"]) == (EMS.version, EMS.hash)
    assert GRAMMAR["signed_drugs_not_sayable"] == []
    assert len(GRAMMAR["words"]) == 748                         # 1,041 with both sets


def test_no_word_only_a_retired_drug_used_is_in_the_grammar():
    pfc = load_bank(PFC_RETIRED, retired_ok=True)
    retired = (pfc.signed_drugs | pfc.silent_drugs) - VOCAB.signed
    names = {t for e in pfc.entries if e["drug"] in retired for t in [e["drug"], *e["aliases"]]}
    only = {w for t in names for w in t.lower().replace("-", " ").split()} - VOCAB.words(signed_only=True)
    assert {"artesunate", "keppra", "levetiracetam", "succinylcholine", "ertapenem"} <= only
    heard = {w for e in GRAMMAR["words"] for w in e.split()}
    assert not only & heard, sorted(only & heard)


def test_every_ems_common_name_names_its_drug():
    for said, generic in MEDIC_NAMES.items():
        assert generic in VOCAB.signed, said
        assert generic in VOCAB.drug_terms.get(said, ()), said
    assert VOCAB.drug_terms["benadryl"] == ("diphenhydramine",)
    assert VOCAB.drug_terms["zofran"] == ("ondansetron",)


def test_a_signed_but_silent_drug_is_heard_and_says_it_cannot_say_its_dose():
    assert boot().handle("bicarb").written == "Sodium bicarbonate is signed, but Pocket cannot say its dose yet."


def test_the_dry_run_covers_the_ems_set_and_hears_no_drug_as_another():
    """Before, with both sets' grammar, the same 258 EMS clips: 246 heard, 0 as another drug."""
    d = json.loads((ROOT / "voice" / "dryrun_drugs.json").read_text())
    assert {r["drug"] for r in d["rows"]} == VOCAB.signed
    assert (d["names"], d["clips"]) == (86, 258)
    assert d["heard"] >= 246 and d["heard_as_another_drug"] == 0


def test_an_indication_longer_than_a_drug_name_is_read_as_the_indication():
    """"calcium channel" (blocker overdose) is an indication; "calcium" is a drug name. The
    longer reading wins, so the indication can be asked for."""
    from grammar.parser import parse
    p = parse("calcium chloride for calcium channel blocker overdose", VOCAB)
    assert [d.generics for d in p.drugs] == [("calcium chloride",)] and p.classes == [VOCAB.class_terms["calcium channel"]]
    assert boot().handle("calcium chloride for calcium channel blocker overdose iv twenty kilos").kind == "readback"


def test_every_indication_term_can_be_said():
    """EMS classes carry punctuation ("TCA / phenobarbital overdose, crush",
    "post-intubation paralysis"); a term with punctuation could never be heard."""
    import re
    assert not [t for t in VOCAB.class_terms if re.search(r"[^a-z ]", t)]
    assert VOCAB.class_terms["phenobarbital overdose"] == "TCA / phenobarbital overdose, crush"
    assert VOCAB.class_terms["post intubation paralysis"] == "post-intubation paralysis"
    assert "crush" not in VOCAB.class_terms                  # one word: fentanyl's crush injury
