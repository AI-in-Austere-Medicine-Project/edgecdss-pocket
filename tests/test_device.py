"""The device loop (voice/device.py): push-to-talk, the session, speech out.

The mic, button, decoders and speaker are stand-ins: the loop is what is tested. The
session is the real one, on the signed bank.
"""
import json
import pathlib

import pytest

from engine.session import HELP_SPOKEN, START_UP_LINE, boot, jsonl_log
from voice import device as dev
from voice import spoken
from voice import speak
from voice.speak import out_format, play_device, tone
from engine.bank import PFC_RETIRED  # the retired PFC set: fixture data (2026-11-23)

ROOT = pathlib.Path(__file__).resolve().parents[1]
BANK = PFC_RETIRED


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
    session = boot(BANK, retired_ok=True, clock=clock, log=log)
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
    assert speaker.said == [START_UP_LINE]


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
    step_one = boot(BANK, retired_ok=True).handle("rsi eighty kilos").text
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


JBL = "2C:FD:B4:DD:BD:A5"


def test_with_the_headset_mic_open_speech_goes_to_the_headset_call_link(monkeypatch):
    # The JBL stalls its A2DP link while its mic (SCO) is open (board, 2026-11-21).
    monkeypatch.delenv("POCKET_PLAY", raising=False)
    assert play_device(JBL) == f"bluealsa:DEV={JBL},PROFILE=sco"


def test_pocket_play_still_wins_over_the_headset(monkeypatch):
    monkeypatch.setenv("POCKET_PLAY", "null")
    assert play_device(JBL) == "null"


def test_the_call_link_is_8_khz_mono_on_cvsd_and_16_khz_on_msbc(monkeypatch):
    codec = {"c": "CVSD"}
    monkeypatch.setattr(speak, "_sco_codec", lambda mac: codec["c"])
    assert out_format(f"bluealsa:DEV={JBL},PROFILE=sco") == (8000, 1)
    codec["c"] = "mSBC"
    assert out_format(f"bluealsa:DEV={JBL},PROFILE=sco") == (16000, 1)


def test_the_a2dp_speaker_stays_44_1_khz_stereo():
    assert out_format(f"bluealsa:DEV={JBL},PROFILE=a2dp") == (44100, 2)
    assert out_format("default") == (44100, 2)


# ── typed in, spoken out (owner, 2026-11-21: until the USB speaker-mic arrives) ──

def test_typed_mode_speaks_the_start_up_line_then_each_answer_in_the_spoken_form(tmp_path):
    speaker = Speaker()
    dev.typed(boot(BANK, retired_ok=True), speaker, ["ketamine for agitation iv 80kg", "", "confirm"], print=lambda *a, **k: None)
    assert speaker.said[0] == START_UP_LINE
    assert speaker.said[1] == "Ketamine, agitation, eye vee, eighty kilos. Confirm?"
    assert speaker.said[2].startswith("Ketamine one hundred and sixty milligrams.")
    assert len(speaker.said) == 3 and speaker.beeps == 0      # a blank line says nothing


def test_typed_mode_runs_rsi(tmp_path):
    speaker = Speaker()
    dev.typed(boot(BANK, retired_ok=True), speaker, ["rsi 80kg", "next", "repeat", "start over"], print=lambda *a, **k: None)
    assert speaker.said[1].startswith("Rapid sequence intubation, adult, eighty kilos. Step one of eleven.")
    assert speaker.said[3] == speaker.said[2] and speaker.said[4] == speaker.said[1]


def test_typed_mode_plays_over_the_music_link_and_opens_no_mic(tmp_path, monkeypatch):
    made = {}

    class FakeSpeaker(Speaker):
        def __init__(self, onnx, device=None, headset=None):
            super().__init__()
            made.update(headset=headset, device=device)
            self.device = "a2dp"
    import voice.speak
    monkeypatch.setattr(voice.speak, "Speaker", FakeSpeaker)
    monkeypatch.setattr(dev, "_lines", lambda: iter(["next"]))
    import voice.listen

    def no_mic(*a):
        raise AssertionError("typed mode opened a mic")
    monkeypatch.setattr(voice.listen, "Mic", no_mic)
    dev.main(["--typed", "--out", str(tmp_path)])
    assert made == {"headset": None, "device": None}
    assert json.loads((tmp_path / "doses.jsonl").read_text().splitlines()[0])["event"] == "boot"


# ── the home menu by voice (owner, 2026-11-21): a press or Enter cuts off anything ──

def test_a_press_cuts_off_help_and_listens_at_once(tmp_path):
    d, speaker = make(tmp_path, ["help", "drugs"], ["down", "down", "down", "down"],
                      stop_on={HELP_SPOKEN})
    run(d, 2)
    assert speaker.said[0] == HELP_SPOKEN and speaker.said[1].startswith("Signed drugs:")
    assert [r["stopped"] for r in heard_log(tmp_path) if "stopped" in r] == [True, False]


class TypedSpeaker(Speaker):
    """Plays until `interrupted()` says Enter was pressed."""
    def say(self, text, interrupted=lambda: False):
        self.said.append(text)
        stopped = interrupted()
        self.stopped = getattr(self, "stopped", []) + [stopped]
        return not stopped


def test_enter_in_typed_mode_cuts_off_what_it_is_saying():
    speaker, presses = TypedSpeaker(), iter([False, True, False])   # Enter during help
    dev.typed(boot(BANK, retired_ok=True), speaker, ["help", "", "home"], print=lambda *a, **k: None,
              interrupted=lambda: next(presses))
    assert speaker.said == [START_UP_LINE, HELP_SPOKEN, "Pocket ready. Say drugs, procedures, or help."]
    assert speaker.stopped == [False, True, False]


class _Pipe:
    def __init__(self):
        self.written = []

    def write(self, b):
        self.written.append(len(b))

    def flush(self):
        pass

    def close(self):
        pass


class _Proc:
    def __init__(self, stdin=None):
        self.stdin = stdin

    def poll(self):
        return 0

    def kill(self):
        pass

    def wait(self):
        pass


def test_a_press_is_seen_within_a_tenth_of_a_second_of_audio_not_at_the_end_of_a_sentence():
    from voice import speak as sp
    s = object.__new__(sp.Speaker)
    s.rate, s.device, s.out_rate, s.out_channels = 16000, "null", 16000, 1
    pipe = _Pipe()
    s._open = lambda: (_Proc(pipe), _Proc())
    checks = []

    def interrupted():
        checks.append(sum(pipe.written))
        return len(checks) > 5
    sentence = bytes(2 * 16000 * 6)                    # one six-second sentence
    assert s._play([sentence], interrupted) is False
    piece = 2 * int(16000 * sp.PIECE_S)
    lead, speech = pipe.written[0], pipe.written[1:]   # the lead-in silence, then the sentence
    assert lead == 2 * int(16000 * sp.LEAD_S)
    assert max(speech) <= piece and sum(speech) <= 5 * piece     # stopped after five pieces
