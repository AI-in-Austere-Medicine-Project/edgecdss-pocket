"""Type phrases at the bench: python3 -m engine [bank_dir]"""
import sys

from engine.session import boot

s = boot(sys.argv[1]) if len(sys.argv) > 1 else boot()
print(s.announce.text)
for line in sys.stdin:
    if line.strip():
        print(s.handle(line).text)
