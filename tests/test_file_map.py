"""The file map (owner, 2026-11-24): "Every folder and file, grouped by folder. One plain-English
line each ... For each: hand-written, generated (and by what), or unused. For each: what depends
on it."

docs/FILE_MAP.md names every file git tracks, and nothing that is not there, so the map
cannot drift as files are added or moved. A row names a file relative to the folder its
heading names; a row such as `fixtures/clips/confirm/kokoro__*.wav` (30 files) stands for
that many files.
"""
import fnmatch
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
MAP = ROOT / "docs" / "FILE_MAP.md"
MADE_BY = re.compile(r"\b(hand|generated|unused)\b")
USED_BY = re.compile(r"\b[SIWTH]\b|unused|everything")


def tracked() -> set:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return {f for f in out.splitlines() if (ROOT / f).exists()}


def rows() -> list:
    """[(path or pattern, count or None, the row's cells)] from every table in the map."""
    folder, out = None, []
    for line in MAP.read_text().splitlines():
        h = re.match(r"#{2,3} (?:`([^`]+)/`|Top level)", line)
        if h:
            folder = h.group(1) + "/" if h.group(1) else ""
            continue
        if line.startswith("## "):
            folder = None                             # a section that is not a folder
        cell = re.match(r"\| `([^`]+)`( \((\d+) files\))? \|(.*)", line)
        if cell and folder is not None:
            cells = [c.strip() for c in cell.group(4).split("|")]
            out.append((folder + cell.group(1), int(cell.group(3)) if cell.group(3) else None, cells))
    return out


def test_every_tracked_file_is_on_the_map_and_every_row_is_a_file():
    files, named = tracked(), set()
    for path, count, _ in rows():
        if count is None:
            assert path in files, f"the map names {path}, which is not in the repo"
            named.add(path)
        else:
            hits = {f for f in files if fnmatch.fnmatchcase(f, path)}
            assert len(hits) == count, f"{path}: the map says {count} files, the repo has {len(hits)}"
            named |= hits
    missing = sorted(files - named)
    assert not missing, f"not on docs/FILE_MAP.md: {missing}"


def test_each_row_says_what_it_does_who_made_it_and_what_uses_it():
    for path, _, cells in rows():
        what, made, used = cells[0], cells[1], cells[2]
        assert what, path
        assert MADE_BY.search(made), f"{path}: made by? {made!r}"
        assert USED_BY.search(used), f"{path}: used by? {used!r}"


def test_the_signed_content_is_marked():
    signed = {p for p, _, cells in rows() if "✍" in cells[0] or "✍" in cells[1]}
    assert {"bank/ems/bank.json", "bank/ems/kit.json", "bank/ems/manifest.json",
            "bank/ems/procedures.json", "docs/WORK_ORDER.md", "grammar/confusable.json"} <= signed
