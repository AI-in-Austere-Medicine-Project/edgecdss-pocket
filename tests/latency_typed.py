#!/usr/bin/env python3
"""Time one typed phrase: text in, what to say out. Parser and engine, no audio.

    python3 tests/latency_typed.py [rounds]

Every phrase in the replay corpus, replayed in order so each runs in its real state.
Session setup is outside the per-phrase clock and reported as boot.
"""
import json
import pathlib
import platform
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.session import boot  # noqa: E402

rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 200
corpus = json.loads((ROOT / "tests" / "replay_corpus.json").read_text())

t = time.perf_counter()
boot(ROOT / "bank")
cold_ms = (time.perf_counter() - t) * 1000

boots, phrase_us = [], []
for _ in range(rounds // 10 or 1):
    t = time.perf_counter()
    boot(ROOT / "bank")
    boots.append((time.perf_counter() - t) * 1000)
session = boot(ROOT / "bank")
for _ in range(rounds):
    for case in corpus:
        session.patient, session.req = type(session.patient)(), type(session.req)()
        session._pending = session._last_entry = None
        for phrase, *_ in case["turns"]:
            t = time.perf_counter()
            session.handle(phrase)
            phrase_us.append((time.perf_counter() - t) * 1e6)

phrase_us.sort()
pct = lambda p: phrase_us[int(len(phrase_us) * p / 100) - 1]
print(f"machine: {platform.machine()} {platform.node()} python {platform.python_version()}")
print(f"phrases timed: {len(phrase_us)} ({rounds} rounds of {sum(len(c['turns']) for c in corpus)})")
print(f"phrase: median {statistics.median(phrase_us):.0f} us, p95 {pct(95):.0f} us, "
      f"p99 {pct(99):.0f} us, max {phrase_us[-1]:.0f} us")
print(f"boot (verify hashes, build word list): cold {cold_ms:.0f} ms, "
      f"median {statistics.median(boots):.0f} ms")
