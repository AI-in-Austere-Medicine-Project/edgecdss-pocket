"""Type phrases at the bench: python3 -m engine [bank_dir]"""
import pathlib
import sys

from engine.session import boot

s = boot(sys.argv[1] if len(sys.argv) > 1 else pathlib.Path(__file__).parents[1] / "bank")
print(s.announce.text)
for line in sys.stdin:
    if line.strip():
        print(s.handle(line).text)
