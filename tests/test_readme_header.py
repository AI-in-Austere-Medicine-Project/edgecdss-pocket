"""The README opens with the header every AI-AMP repo shares (owner, 2026-11-16, item 6):
name, one-line description, the notice, and links to the site, the portal and Substack."""
import pathlib

README = (pathlib.Path(__file__).resolve().parents[1] / "README.md").read_text()

HEADER = """# EdgeCDSS Pocket

A wearable voice dose assistant. Signed doses only, no language model, no network.

> **Research prototype.** Not for patient care. Simulated scenarios only. Enter no patient information.

[Project site](https://ai-in-austere-medicine-project.github.io/pi-cloud-cdss/web/) · [Portal](https://cdss.arcanekg.com) · [Substack](https://aiamp.substack.com)
"""


def test_the_readme_opens_with_the_shared_header():
    assert README.startswith(HEADER)


def test_the_notice_is_stated_once():
    assert README.count("Research prototype") == 1
