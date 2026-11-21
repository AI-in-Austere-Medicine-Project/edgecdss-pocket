"""Every word Pocket speaks by name, numbered, one at a time: for the owner to note the ones
that sound wrong (owner, 2026-11-21).

  sudo systemctl stop pocket          # the session holds the speaker and its button
  ~/pocket-venv/bin/python -m voice.tools.say_all [--from N] [--only 3,7,12] [--pause S]
  sudo systemctl start pocket

Says "Number N." then the word, as Pocket says it in its answers: the drug names (each
signed drug, and every other name it is asked for by), the routes, the procedure names
and the command words. The same list, with what is shown and what is said, is printed.
The numbers do not move while the bank, the vocabulary and the spoken forms stay the
same, so "7, 12" means the same words the next time.
"""
import argparse
import pathlib
import time

from engine import words
from engine.bank import load_bank
from grammar.vocabulary import CONTROLS, PROCEDURE_TITLES, build

ROOT = pathlib.Path(__file__).resolve().parents[2]


def items(bank_dir=ROOT / "bank") -> list:
    """[(n, group, written, spoken)], numbered from 1."""
    bank = load_bank(bank_dir)
    vocab = build(bank)
    rows = []
    signed = sorted(bank.signed_drugs, key=words.say_name)
    for d in signed:
        rows.append(("drug", d, words.say_name(d)))
    others = sorted(t for t, g in vocab.signed_terms().items()
                    if len(g) == 1 and t != words.say_name(g[0]).lower() and t not in signed)
    for t in others:
        rows.append(("drug name", t, words.say_name(t)))
    for letters, said in words.ROUTE_WORDS.items():
        rows.append(("route", letters, said))
    for title in PROCEDURE_TITLES.values():
        rows.append(("procedure", title, title))
    rows.append(("procedure", "RSI", "R S I"))
    for c in CONTROLS:
        rows.append(("command", c, c))
    return [(i, *r) for i, r in enumerate(rows, 1)]


def run(speaker, rows, pause=1.5, sleep=time.sleep, print=print) -> None:
    for n, group, written, said in rows:
        said = words.say_as(said)
        print(f"{n:3d}. [{group}] {written}" + (f"  (said: {said})" if said != written else ""), flush=True)
        speaker.say(f"Number {words.num(n)}. {said}.")
        sleep(pause)


def pick(rows, start=1, only=None) -> list:
    keep = set(only) if only else None
    return [r for r in rows if r[0] >= start and (keep is None or r[0] in keep)]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--from", dest="start", type=int, default=1)
    ap.add_argument("--only", help="numbers, comma separated: just these")
    ap.add_argument("--pause", type=float, default=1.5)
    ap.add_argument("--list", action="store_true", help="print the list, say nothing")
    a = ap.parse_args(argv)
    rows = pick(items(), a.start, [int(x) for x in a.only.split(",")] if a.only else None)
    if a.list:
        run(_Silent(), rows, 0, sleep=lambda s: None)
        return
    from voice import device
    from voice.speak import Speaker
    speaker = Speaker(device.PIPER)
    print(f"speaker: {speaker.device}; {len(rows)} words", flush=True)
    run(speaker, rows, a.pause)


class _Silent:
    def say(self, text, interrupted=lambda: False):
        return True


if __name__ == "__main__":
    main()
