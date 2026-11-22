"""The numbered list of every word Pocket says by name (owner, 2026-11-21):
voice/tools/say_all.py, and the spoken spellings that fix one (engine/words.SAY_AS).

Owner: "Give me one command on the board that speaks every drug name, route, procedure
name and command word, one at a time, numbered, so I can note the ones that sound wrong.
I will give you the numbers; you fix them with a spoken spelling and I listen again."
"""
from engine import words
from engine.bank import load_bank
from engine.session import boot
from grammar.vocabulary import CONTROLS
from voice.tools import say_all

ROWS = say_all.items()


class Speaker:
    def __init__(self):
        self.said = []

    def say(self, text, interrupted=lambda: False):
        self.said.append(text)
        return True


def test_it_lists_every_drug_name_route_procedure_and_command_numbered():
    groups = {}
    for n, group, written, _ in ROWS:
        groups.setdefault(group, []).append(written)
    assert [r[0] for r in ROWS] == list(range(1, len(ROWS) + 1))
    sets = [load_bank(say_all.ROOT / "bank"), load_bank(say_all.ROOT / "bank" / "ems")]   # both sets (2026-11-22)
    assert len(groups["drug"]) == len(set().union(*(b.signed_drugs | b.silent_drugs for b in sets))) == 45
    assert {"narcan", "versed", "txa", "epi", "levophed", "benadryl", "zofran", "bicarb"} <= set(groups["drug name"])
    assert groups["route"] == ["IV", "IM", "IO", "IN", "PO", "NEB"]
    assert groups["procedure"] == ["rapid sequence intubation", "failed airway", "RSI"]
    assert groups["command"] == list(CONTROLS)


def test_the_numbers_stay_the_same_from_run_to_run():
    assert say_all.items() == ROWS
    assert ROWS[0][2] == "acetaminophen" and ROWS[113][2:] == ("IV", "eye vee")


def test_each_word_is_said_numbered_as_pocket_says_it():
    sp, out = Speaker(), []
    say_all.run(sp, say_all.pick(ROWS, only=[1, 43, 114, 122, 147]), pause=0, sleep=lambda s: None,
                print=lambda line, **k: out.append(line))
    assert sp.said == ["Number one. acetaminophen.", "Number forty-three. sodium chloride three percent.",
                       "Number one hundred and fourteen. eye vee.", "Number one hundred and twenty-two. R S I.",
                       "Number one hundred and forty-seven. E M S set."]
    assert out[2].startswith("114. [route] IV  (said: eye vee)")


def test_from_restarts_part_way():
    assert [r[0] for r in say_all.pick(ROWS, start=146)] == [146, 147, 148]


def test_a_spoken_spelling_changes_what_is_said_and_never_what_is_shown(monkeypatch):
    monkeypatch.setattr(words, "SAY_AS", {"phytomenadione": "fy toe menna dye own",
                                          "norepinephrine": "nor eppy neff rin"})
    turn = boot(say_all.ROOT / "bank").handle("epinephrine", spoken=True)
    assert turn.text == "Epinephrine or nor eppy neff rin?"            # said
    assert turn.written_text == "Epinephrine or norepinephrine?"       # shown
    sp = Speaker()
    say_all.run(sp, say_all.pick(ROWS, only=[38]), pause=0, sleep=lambda s: None, print=lambda *a, **k: None)
    assert sp.said == ["Number thirty-eight. fy toe menna dye own."]


def test_no_spoken_spelling_is_set_until_the_owner_has_listened():
    assert words.SAY_AS == {}
