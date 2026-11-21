"""Pocket on power-up (owner, 2026-11-21): voice/autostart.py, device/pocket.service and
device/install.sh.

Owner: "the Radxa starts Pocket by itself on power-up. No login, no keyboard, no network
needed. 1. A service on the board starts at boot and runs the voice session from
~/edgecdss-pocket (main). It restarts itself if it crashes. 2. Bluetooth: connect to the
paired speaker automatically and keep retrying, since the speaker may be switched on
after the board. When it connects, speak the start-up line. If the speaker drops and
comes back, reconnect and say "Pocket ready." 3. Microphone: use the USB mic when one is
plugged in. If there is none, say "No microphone found" through the speaker instead of
failing silently. 4. It must work with Wi-Fi and Tailscale unavailable. 5. Power can be
cut at any time. Make sure a sudden power-off does not corrupt the card or the dose log
... 6. An install script sets all this up on a fresh board ..."

The board (Bluetooth, sound cards, the button, the clock) is a stand-in here; the session
is the real one, on the signed bank. On the board itself: device/RADXA.md.
"""
import json
import os
import pathlib
import re
import subprocess

import pytest

from engine.session import START_UP_LINE, boot, jsonl_log
from voice import autostart as au

ROOT = pathlib.Path(__file__).resolve().parents[1]
BANK = ROOT / "bank"
JBL = "2C:FD:B4:DD:BD:A5"
MIC = ["arecord", "-q", "-D", "plughw:CARD=Microphone,DEV=0"]


class Stop(Exception):
    pass


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class Button:
    """Scripted polls; the clock moves by each poll's timeout. At the end of the script,
    `then()` runs (the speaker is switched off, say), then polls go quiet."""
    mode = "toggle"

    def __init__(self, clock, script=(), then=None):
        self.clock, self.script, self.then = clock, list(script), then

    def poll(self, timeout):
        self.clock.t += max(timeout, 0.05)
        if self.script:
            return self.script.pop(0)
        if self.then:
            then, self.then = self.then, None
            then()
        return None

    def drain(self):
        pass


class Board:
    def __init__(self, clock, on_after=0, mic=MIC, button=True):
        self.clock, self.on_after, self.mic_cmd = clock, on_after, mic
        self.connected, self.connects, self.has_button = None, 0, button
        self.button_obj = None
        self.paired = [JBL]

    def connected_speaker(self):
        return self.connected

    def paired_speakers(self):
        return list(self.paired)

    def connect(self, mac):
        self.connects += 1
        if self.connects > self.on_after:
            self.connected = mac

    def mic(self):
        return self.mic_cmd

    def button(self):
        return (self.button_obj, "JBL Clip 3 (AVRCP)") if self.has_button else (None, None)

    def uptime(self):
        return 10.0 + self.clock.t

    def boot_id(self):
        return "b00t1d"


class Speaker:
    def __init__(self):
        self.said, self.device = [], "null"

    def say(self, text, interrupted=lambda: False):
        self.said.append(text)
        return True

    def beep(self):
        pass


class Mic:
    def __init__(self, cmd):
        self.cmd, self.open, self.live = cmd, True, True

    def alive(self):
        return self.live

    def start(self, sink, pre_roll=True):
        sink(b"\0" * 640)

    def stop(self):
        pass

    def close(self):
        self.open = False


class Hearing:
    def __init__(self, heard):
        self.heard = list(heard)

    def start(self):
        heard = self.heard.pop(0) if self.heard else ""
        return _U(heard)


class _U:
    def __init__(self, heard):
        self.heard = heard

    def feed(self, d):
        pass

    def finish(self):
        return self.heard, self.heard, "spelled"


def make(tmp_path, board=None, heard=(), log=None):
    clock = Clock()
    board = board or Board(clock)
    board.clock = clock
    speaker = Speaker()
    sleeps = []

    def sleep(s):
        sleeps.append(s)
        clock.t += s
        if len(sleeps) > 500:
            raise Stop

    mics = []

    def make_mic(cmd):
        mics.append(Mic(cmd))
        return mics[-1]
    session = boot(BANK, log=log)
    p = au.Pocket(board, session, Hearing(heard), speaker, tmp_path, make_mic=make_mic,
                  clock=clock, sleep=sleep, say_log=lambda *a, **k: None)
    return p, board, speaker, clock, sleeps, mics


def events(tmp_path):
    return [json.loads(x)["event"] for x in (tmp_path / "autostart.jsonl").read_text().splitlines()]


def lose_speaker(board):
    def off():
        board.connected = None
    return off


# ── 2. the speaker ──────────────────────────────────────────────────────────

def test_it_keeps_asking_the_paired_speaker_to_connect_then_says_the_start_up_line(tmp_path):
    clock = Clock()
    board = Board(clock, on_after=3)                    # switched on after three tries
    p, board, speaker, clock, sleeps, _ = make(tmp_path, board)
    board.button_obj = Button(clock, then=lose_speaker(board))
    p.run(forever=False)
    assert board.connects == 4 and sleeps.count(au.SPEAKER_RETRY_S) == 3
    assert speaker.said[0] == START_UP_LINE
    assert speaker.device == f"bluealsa:DEV={JBL},PROFILE=a2dp"
    assert events(tmp_path)[:1] == ["ready"] and "speaker_lost" in events(tmp_path)


def test_a_speaker_that_drops_and_comes_back_hears_pocket_ready(tmp_path):
    p, board, speaker, clock, _, _ = make(tmp_path)
    board.button_obj = Button(clock, then=lose_speaker(board))
    p.run(forever=False)                                # connected, then dropped
    board.button_obj = Button(clock, then=lose_speaker(board))
    p.run(forever=False)                                # back again
    assert speaker.said == [START_UP_LINE, au.READY]
    assert events(tmp_path).count("speaker_lost") == 2


def test_a_speaker_already_connected_is_used_without_asking(tmp_path):
    p, board, speaker, clock, _, _ = make(tmp_path)
    board.connected = JBL
    board.button_obj = Button(clock, then=lose_speaker(board))
    p.run(forever=False)
    assert board.connects == 0 and speaker.said[0] == START_UP_LINE


def test_the_paired_speakers_are_the_paired_devices_that_take_audio(monkeypatch):
    out = {("bluetoothctl", "devices", "Paired"): f"Device {JBL} JBL Clip 3\nDevice AA:BB:CC:DD:EE:FF Phone\n",
           ("bluetoothctl", "info", JBL): "\tUUID: Audio Sink (0000110b-...)\n",
           ("bluetoothctl", "info", "AA:BB:CC:DD:EE:FF"): "\tUUID: Handsfree Audio Gateway\n",
           ("bluealsa-cli", "list-pcms"): f"/org/bluealsa/hci0/dev_{JBL.replace(':', '_')}/a2dpsrc/sink\n"}
    monkeypatch.delenv("POCKET_SPEAKER", raising=False)
    b = au.Board(run=lambda cmd, timeout=20: out.get(tuple(cmd), ""))
    assert b.paired_speakers() == [JBL] and b.connected_speaker() == JBL
    monkeypatch.setenv("POCKET_SPEAKER", "11:22:33:44:55:66")
    assert b.paired_speakers() == ["11:22:33:44:55:66"]


# ── 3. the microphone ───────────────────────────────────────────────────────

def test_no_mic_is_said_then_a_press_says_it_again_and_a_mic_plugged_in_is_used(tmp_path):
    clock = Clock()
    board = Board(clock, mic=None)
    p, board, speaker, clock, _, mics = make(tmp_path, board, heard=["drugs"])

    def plug_in():
        board.mic_cmd = MIC
    board.button_obj = Button(clock, script=[None, "down", None], then=plug_in)
    # after the mic: one press-press turn ("drugs"), then the speaker goes
    orig = board.button_obj.poll
    turns = iter([None, "down", "down"])

    def poll(timeout):
        if board.mic_cmd is None:
            return orig(timeout)
        clock.t += max(timeout, 0.05)
        r = next(turns, "gone")
        if r == "gone":
            board.connected = None
            return None
        return r
    board.button_obj.poll = poll
    p.run(forever=False)
    assert speaker.said[:4] == [START_UP_LINE, au.NO_MIC, au.NO_MIC, au.READY]
    assert speaker.said[4].startswith("Signed drugs:")
    assert mics[0].cmd == MIC and not mics[0].open
    assert events(tmp_path)[:3] == ["ready", "no_mic", "mic_found"]


def test_a_mic_pulled_out_says_no_mic_found(tmp_path):
    p, board, speaker, clock, _, mics = make(tmp_path)
    state = {"n": 0}

    def poll(timeout):
        clock.t += max(timeout, 0.05)
        state["n"] += 1
        if state["n"] == 3:
            mics[-1].live = False                       # pulled out
            board.mic_cmd = None
        if state["n"] > 400:
            board.connected = None
        return None
    board.button_obj = Button(clock)
    board.button_obj.poll = poll
    p.run(forever=False)
    assert speaker.said[:2] == [START_UP_LINE, au.NO_MIC]
    assert "mic_lost" in events(tmp_path) and not mics[0].open


def test_the_usb_mic_is_the_first_usb_card_that_records(tmp_path):
    hdmi, usb, usb_out = tmp_path / "card0", tmp_path / "card1", tmp_path / "card2"
    for card, cid in ((hdmi, "rockchiphdmi"), (usb, "Microphone"), (usb_out, "Speaker")):
        card.mkdir()
        (card / "id").write_text(cid + "\n")
    (hdmi / "pcm0p").mkdir()
    assert au.usb_capture(tmp_path) is None                  # the board today: HDMI only
    (usb_out / "usbid").write_text("1234:5678\n")
    (usb_out / "pcm0p").mkdir()
    assert au.usb_capture(tmp_path) is None                  # USB, but plays only
    (usb / "usbid").write_text("12d1:0010\n")
    (usb / "pcm0c").mkdir()
    assert au.usb_capture(tmp_path) == ["arecord", "-q", "-D", "plughw:CARD=Microphone,DEV=0", "-t", "raw",
                                        "-f", "S16_LE", "-r", "16000", "-c", "1"]


def test_no_button_is_said_once_and_it_keeps_looking(tmp_path):
    clock = Clock()
    board = Board(clock, button=False)
    p, board, speaker, clock, sleeps, _ = make(tmp_path, board)

    def sleep(s):
        clock.t += s
        if clock.t > au.BUTTON_WAIT_S + 5:
            board.connected = None
    p.sleep = sleep
    p.run(forever=False)
    assert speaker.said == [START_UP_LINE, au.NO_BUTTON]


def test_a_button_whose_device_is_gone_is_a_lost_speaker():
    class Gone:
        mode = "toggle"

        def poll(self, timeout):
            raise OSError(19, "No such device")
    clock = Clock()
    w = au.Watched(Gone(), Board(clock), JBL, None, clock)
    with pytest.raises(au.SpeakerLost):
        w.poll(0.5)


# ── the dose log, power and the clock ───────────────────────────────────────

def test_a_dose_by_voice_on_power_up_is_logged_with_the_boot_id_and_uptime(tmp_path):
    clock = Clock()
    board = Board(clock)
    log = au.stamped_log(tmp_path / "doses.jsonl", board)
    p, board, speaker, clock, _, _ = make(tmp_path, board, heard=["ketamine for agitation i v eighty kilos",
                                                                   "confirm"], log=log)
    seq = iter([None, "down", "down", "down", "down"])

    def poll(timeout):
        clock.t += max(timeout, 0.05)
        r = next(seq, None)
        if r is None and clock.t > 50:
            board.connected = None
        return r
    board.button_obj = Button(clock)
    board.button_obj.poll = poll
    p.run(forever=False)
    lines = [json.loads(x) for x in (tmp_path / "doses.jsonl").read_text().splitlines()]
    assert [x.get("event") for x in lines] == ["boot", None]
    assert lines[1]["drug"] == "ketamine"
    assert all(x["boot_id"] == "b00t1d" and x["uptime_s"] >= 10 for x in lines)
    assert any(s.startswith("Ketamine one hundred and sixty milligrams.") for s in speaker.said)


def test_the_dose_log_fsyncs_each_line_and_the_directory_once(tmp_path, monkeypatch):
    import stat
    synced, real = [], os.fsync

    def fsync(fd):
        synced.append(stat.S_ISDIR(os.fstat(fd).st_mode))     # True: the directory
        real(fd)
    monkeypatch.setattr(os, "fsync", fsync)
    write = jsonl_log(tmp_path / "doses.jsonl")
    write({"a": 1})
    write({"a": 2})
    assert synced == [False, True, False]        # line, directory, line


# ── 1, 4. the service ───────────────────────────────────────────────────────

UNIT = (ROOT / "device" / "pocket.service").read_text()


def _section(name):
    return re.search(rf"\[{name}\]\n(.*?)(?=\n\[|\Z)", UNIT, re.S).group(1)


def test_the_service_starts_at_boot_runs_the_session_from_the_repo_and_restarts():
    service = _section("Service")
    assert "ExecStart=@HOME@/pocket-venv/bin/python -m voice.autostart" in service
    assert "WorkingDirectory=@HOME@/edgecdss-pocket" in service and "User=@USER@" in service
    assert "Restart=always" in service
    assert "StartLimitIntervalSec=0" in _section("Unit")       # [Unit]: not ignored
    assert "StartLimit" not in service
    assert "WantedBy=multi-user.target" in _section("Install")


def test_the_service_waits_for_bluetooth_and_never_for_the_network():
    unit = _section("Unit")
    assert "bluetooth.service" in unit and "bluealsa.service" in unit
    assert not re.search(r"(?i)network|tailscale|wpa|NetworkManager", UNIT.split("[Unit]")[1])


def test_the_power_up_code_uses_no_network():
    src = (ROOT / "voice" / "autostart.py").read_text()
    assert not re.search(r"\b(socket|urllib|requests|http|curl|tailscale|nmcli)\b", src)


# ── 5, 6. the install script ────────────────────────────────────────────────

INSTALL = ROOT / "device" / "install.sh"


def test_the_install_script_is_valid_bash():
    subprocess.run(["bash", "-n", str(INSTALL)], check=True)


def test_the_install_script_does_every_step_and_checks_what_it_downloads():
    s = INSTALL.read_text()
    for step in ("bluez-alsa", "--enable-msbc", "--enable-cli", "pocket-hfp.conf", "--a2dp-force-audio-cd",
                 "vosk==0.3.45", "piper-tts==1.8.0", "sha256sum -c", "bluetoothctl trust",
                 "usermod -aG audio,bluetooth,input", "speexrate_medium", "systemctl enable pocket.service",
                 "@USER@", "@HOME@"):
        assert step in s, step
    assert "30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498" in s     # the Vosk model
    assert "f7d01dde371555732c4c314111ac79672b1a5ce2fc19266ab42178fd8df7f375" in s     # the Piper voice


def test_the_install_script_makes_a_power_cut_safe_for_the_card():
    s = INSTALL.read_text()
    assert "swapoff -a" in s and "no swap on the card" in s
    assert "Storage=volatile" in s
    assert "noatime" in s
    for timer in ("apt-daily.timer", "apt-daily-upgrade.timer"):
        assert timer in s
    assert "rm -rf" not in s and "rm -f /swapfile" not in s        # nothing deleted


def test_the_install_script_edits_fstab_only_as_intended(tmp_path):
    """Its two fstab edits, run on this board's fstab: swap commented out, noatime added."""
    fstab = tmp_path / "fstab"
    fstab.write_text("UUID=21BD-9125 /config vfat defaults,x-systemd.automount 0 2\n"
                     "UUID=d3e1 / ext4 defaults 0 1\n/swapfile none swap sw,pri=10 0 0\n")
    s = INSTALL.read_text()
    edits = re.findall(r"sudo sed -i -E '([^']+)' /etc/fstab", s)
    assert len(edits) == 2
    for e in edits:
        subprocess.run(["sed", "-i", "-E", e, str(fstab)], check=True)
    lines = fstab.read_text().splitlines()
    assert lines[1] == "UUID=d3e1 / ext4 defaults,noatime 0 1"
    assert lines[2].startswith("# pocket: no swap on the card # /swapfile")
    assert lines[0] == "UUID=21BD-9125 /config vfat defaults,x-systemd.automount 0 2"



def test_the_voice_loads_while_the_speaker_connects_and_is_waited_for_before_speaking(tmp_path):
    import threading
    gate, made = threading.Event(), []

    def make_speaker():
        gate.wait(5)
        made.append(Speaker())
        return made[-1]
    p, board, _, clock, _, _ = make(tmp_path)
    p.speaker = au.Later(make_speaker)
    board.button_obj = Button(clock, then=lose_speaker(board))
    connects_before = []
    real_connect = board.connect

    def connect(mac):
        connects_before.append(bool(made))
        real_connect(mac)
        gate.set()                                   # the voice finishes after the connect
    board.connect = connect
    p.run(forever=False)
    assert connects_before == [False]                # it asked the speaker while loading
    assert made and made[0].said[0] == START_UP_LINE


def test_a_voice_that_fails_to_load_fails_the_service_so_it_restarts(tmp_path):
    p, board, _, clock, _, _ = make(tmp_path)

    def broken():
        raise RuntimeError("no voice")
    p.speaker = au.Later(broken)
    with pytest.raises(RuntimeError, match="no voice"):
        p.run(forever=False)


def test_the_voice_says_when_it_has_loaded():
    done = []
    later = au.Later(lambda: "voice", done=lambda: done.append(True))
    assert later.get() == "voice" and done == [True]
