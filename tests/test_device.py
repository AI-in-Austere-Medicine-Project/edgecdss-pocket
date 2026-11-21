"""The device loop (voice/device.py): push-to-talk, the session, speech out.

The mic, button, decoders and speaker are stand-ins: the loop is what is tested. The
session is the real one, on the signed bank.
"""
import json
import pathlib

import pytest

from engine.session import boot, jsonl_log
from voice import device as dev
from voice import spoken
from voice.speak import play_device, tone

ROOT = pathlib.Path(__file__).resolve().parents[1]
BANK = ROOT / "bank"


class Done(Exception):
    pass


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class Button:
    """Scripted poll results; None for an empty poll. Time moves by each poll's timeout."""

    def __init__(self, script, clock, mode="toggle"):
        self.script, self.clock, self.mode = list(script), clock, mode
        self.drained = 0

    def poll(self, timeout):
        self.clock.t += timeout
        if not self.script:
            raise Done
        return self.script.pop(0)

    def drain(self):
        self.drained += 1


class Mic:
    def __init__(self):
        self.pre_roll = []

    def start(self, sink, pre_roll=True):
        self.pre_roll.append(pre_roll)
        sink(b"\0" * 640)

    def stop(self):
        pass


class Hearing:
    """Each utterance is heard as the next scripted Vosk text."""

    def __init__(self, heard):
        self.heard = list(heard)

    def start(self):
        heard = self.heard.pop(0)
        return _Utterance(heard)


class _Utterance:
    def __init__(self, heard):
        self.heard = heard

    def feed(self, data):
        pass

    def finish(self):
        return self.heard, spoken.normalise(self.heard), "spelled"


class Speaker:
    def __init__(self, stop_on=()):
        self.said, self.beeps, self.stop_on = [], 0, set(stop_on)

    def say(self, text, interrupted=lambda: False):
        self.said.append(text)
        return not (text in self.stop_on and interrupted())

    def beep(self):
        self.beeps += 1


def make(tmp_path, heard, script, mode="toggle", stop_on=(), log=None):
    clock = Clock()
    session = boot(BANK, clock=clock, log=log)
    speaker = Speaker(stop_on)
    d = dev.Device(session, Hearing(heard), Mic(), Button(script, clock, mode), speaker, tmp_path,
                   clock=clock, now=lambda: "2026-11-21T12:00:00Z")
    return d, speaker


def run(d, turns):
    for _ in range(turns):
        d.turn()


def heard_log(tmp_path):
    return [json.loads(x) for x in (tmp_path / "heard.jsonl").read_text().splitlines()]


# ── speaking ────────────────────────────────────────────────────────────────

def test_it_starts_by_saying_the_short_start_up_line(tmp_path):
    d, speaker = make(tmp_path, [], [])
    d.start()
    assert speaker.said == ["PFC set, version one point four point zero."]


def test_a_press_a_beep_then_what_is_heard_is_answered_aloud_in_the_spoken_form(tmp_path):
    d, speaker = make(tmp_path, ["ketamine for agitation i v eighty kilos"], ["down", "down"])
    run(d, 1)
    assert speaker.beeps == 1
    assert speaker.said == ["Ketamine, agitation, eye vee, eighty kilos. Confirm?"]
    rec = heard_log(tmp_path)[0]
    assert rec["heard"] == "ketamine for agitation i v eighty kilos" and rec["kind"] == "readback"
    assert rec["written"] == "Ketamine, agitation, IV, eighty kilos. Confirm?"
    assert (tmp_path / "001.wav").exists()


def test_the_beep_is_not_recorded(tmp_path):
    d, _ = make(tmp_path, ["next"], ["down", "down"])
    run(d, 1)
    assert d.mic.pre_roll == [False]


def test_what_is_heard_is_handled_as_heard_so_a_confused_pair_asks_first(tmp_path):
    d, speaker = make(tmp_path, ["epinephrine"], ["down", "down"])
    run(d, 1)
    assert speaker.said == ["Epinephrine or norepinephrine?"]


def test_nothing_heard_says_so_and_leaves_the_session_alone(tmp_path):
    d, speaker = make(tmp_path, ["ketamine for agitation i v eighty kilos", ""],
                      ["down", "down", "down", "down"])
    run(d, 2)
    assert speaker.said[-1] == dev.NOT_HEARD
    assert d.session._pending is not None          # the read-back still waits


def test_a_dose_by_voice_is_logged_after_the_start_up_line(tmp_path):
    log = tmp_path / "doses.jsonl"
    d, speaker = make(tmp_path, ["ketamine for agitation i v eighty kilos", "confirm"],
                      ["down", "down", "down", "down"], log=jsonl_log(log))
    run(d, 2)
    assert speaker.said[-1].startswith("Ketamine one hundred and sixty milligrams.")
    lines = [json.loads(x) for x in log.read_text().splitlines()]
    assert [x.get("event") for x in lines] == ["boot", None]
    assert lines[1]["drug"] == "ketamine"


# ── the button ──────────────────────────────────────────────────────────────

def test_hold_mode_listens_until_the_key_comes_up(tmp_path):
    d, speaker = make(tmp_path, ["next"], ["down", None, None, "up"], mode="hold")
    run(d, 1)
    assert speaker.said == ["No steps running."]
    assert d.button.drained == 0                    # a quick release is never thrown away


def test_toggle_mode_drops_the_key_up_and_stops_on_the_next_press(tmp_path):
    d, speaker = make(tmp_path, ["next"], ["down", "up", None, "down"])
    run(d, 1)
    assert speaker.said == ["No steps running."] and d.button.drained == 1


def test_a_second_press_that_never_comes_stops_listening_after_the_limit(tmp_path):
    d, speaker = make(tmp_path, ["next"], ["down"] + [None] * 400)
    run(d, 1)
    assert speaker.said == ["No steps running."]
    assert d.clock() >= dev.MAX_LISTEN_S


def test_a_press_while_it_speaks_stops_it_and_listens_at_once(tmp_path):
    step_one = boot(BANK).handle("rsi eighty kilos").text
    # press, press (heard), a press during step one, press (heard "next")
    d, speaker = make(tmp_path, ["r s i eighty kilos", "next"], ["down", "down", "down", "down"],
                      stop_on={step_one})
    run(d, 2)
    assert speaker.said == [step_one, speaker.said[1]] and speaker.beeps == 2
    assert speaker.said[1].startswith("Step two of eleven.")
    stopped = [r["stopped"] for r in heard_log(tmp_path) if "stopped" in r]
    assert stopped == [True, False]


# ── a read-back left waiting ────────────────────────────────────────────────

def test_a_read_back_left_waiting_is_cancelled_aloud_once(tmp_path):
    d, speaker = make(tmp_path, ["ketamine for agitation i v eighty kilos", "yes"],
                      ["down", "down"] + [None] * 70 + ["down", "down"])
    run(d, 2)
    assert speaker.said.count("Cancelled.") == 1
    assert speaker.said[-1] == "Nothing to confirm."
    assert [r.get("event") for r in heard_log(tmp_path)].count("expired") == 1


# ── RSI by voice ────────────────────────────────────────────────────────────

def test_rsi_by_voice_steps_repeat_and_start_over(tmp_path):
    heard = ["r s i", "eighty kilos", "next", "repeat", "start over"]
    d, speaker = make(tmp_path, heard, ["down", "down"] * len(heard))
    run(d, len(heard))
    assert speaker.said[0] == "Weight?"
    assert speaker.said[1].startswith("Rapid sequence intubation, adult, eighty kilos. Step one of eleven.")
    assert speaker.said[2].startswith("Step two of eleven.")
    assert speaker.said[3] == speaker.said[2]
    assert speaker.said[4] == speaker.said[1]


def test_failed_airway_by_voice_asks_and_reads_the_answer(tmp_path):
    heard = ["failed airway", "next", "next", "no"]
    d, speaker = make(tmp_path, heard, ["down", "down"] * len(heard))
    run(d, len(heard))
    assert speaker.said[2] == "Can you mask ventilate? Say yes or no."
    assert speaker.said[3].startswith("Step three of three. NO, then Emergency pathway.")


# ── the speaker ─────────────────────────────────────────────────────────────

def test_the_play_device_is_pocket_play_when_set(monkeypatch):
    monkeypatch.setenv("POCKET_PLAY", "null")
    assert play_device() == "null"


def test_the_beep_is_a_short_faded_tone():
    pcm = tone(16000, 880.0, 0.12)
    assert len(pcm) == 2 * 1920 and pcm[:2] == b"\0\0"
