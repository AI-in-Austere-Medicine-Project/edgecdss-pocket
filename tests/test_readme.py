"""The README's worked example is the engine's own output, word for word."""
import pathlib
import re

from engine.session import boot

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_the_readme_example_is_what_the_engine_says():
    readme = (ROOT / "README.md").read_text()
    pairs = re.findall(r'Say "([^"]+)" It says "([^"]+)"', readme)
    assert len(pairs) >= 2
    s = boot(ROOT / "bank")
    for phrase, said in pairs:
        assert s.handle(phrase).say == said, phrase
