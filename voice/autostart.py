"""Pocket on power-up (owner, 2026-11-21): no login, no keyboard, no network.

  python3 -m voice.autostart        (run by pocket.service at boot; device/install.sh)

The models load once. Then, for as long as the board has power:
  - the speaker: the connected A2DP speaker, else each paired one is asked to connect,
    every SPEAKER_RETRY_S, since it may be switched on after the board. On connecting,
    the start-up line ("Pocket ready. Research prototype ..."); on coming back after a
    drop, "Pocket ready." The speaker's own button is push-to-talk (toggle: the JBL).
  - the mic: a USB sound card that can record. None: "No microphone found." through the
    speaker, again on a press, and a check every MIC_RETRY_S until one is plugged in.
  - then the voice session (voice/device.py), the same session for the whole power-on:
    a drop of the speaker or the mic goes back to waiting for it, and nothing is lost.

A dose is logged (and fsynced, rule 3) before it is spoken. The board keeps no time
without the network (no battery clock), so every log line also carries this power-on's
boot id and the seconds since power-on: the order of doses within a power-on is exact
even when the clock is not.

  POCKET_SPEAKER  the speaker's MAC (default: any paired A2DP speaker)
  POCKET_CAPTURE  a capture command, as in voice/listen.py (default: the USB mic)
"""
import datetime
import json
import os
import pathlib
import subprocess
import time

from engine.session import boot, jsonl_log
from voice import device as dev

ROOT = pathlib.Path(__file__).resolve().parents[1]
READY = "Pocket ready."
NO_MIC = "No microphone found."
NO_BUTTON = "No button found."
SPEAKER_RETRY_S = 5.0
MIC_RETRY_S = 3.0
CHECK_S = 2.0           # while listening or idle: is the speaker still there, the mic?
SETTLE_S = 1.5          # a speaker just connected drops the first second it is sent
BUTTON_WAIT_S = 10.0    # the speaker's button appears as an input device just after it


class SpeakerLost(Exception):
    pass


class MicLost(Exception):
    pass


# ── the board ───────────────────────────────────────────────────────────────

def _run(cmd, timeout=20) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


class Board:
    """Bluetooth, sound cards and the clock, as the Radxa has them. Tests replace it."""

    def __init__(self, run=_run):
        self.run = run

    def connected_speaker(self):
        """The MAC of the A2DP speaker bluez-alsa is connected to, or None."""
        for line in self.run(["bluealsa-cli", "list-pcms"]).split():
            if line.endswith("/a2dpsrc/sink"):
                return line.split("/")[4][4:].replace("_", ":")
        return None

    def paired_speakers(self) -> list:
        if os.getenv("POCKET_SPEAKER"):
            return [os.environ["POCKET_SPEAKER"]]
        out = []
        for line in self.run(["bluetoothctl", "devices", "Paired"]).splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == "Device":
                if "Audio Sink" in self.run(["bluetoothctl", "info", parts[1]]):
                    out.append(parts[1])
        return out

    def connect(self, mac) -> None:
        self.run(["bluetoothctl", "connect", mac], timeout=15)

    def mic(self, cards="/proc/asound"):
        """A capture command for the first USB sound card that records, or None."""
        if os.getenv("POCKET_CAPTURE"):
            return os.environ["POCKET_CAPTURE"].split()
        return usb_capture(pathlib.Path(cards))

    def button(self):
        from voice import listen
        path, name = listen.find_button()
        return (listen.Button(path, "toggle"), name) if path else (None, None)

    def uptime(self) -> float:
        return time.clock_gettime(time.CLOCK_BOOTTIME)

    def boot_id(self) -> str:
        try:
            return pathlib.Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        except OSError:
            return ""

    def clock_synchronized(self) -> bool:
        return "yes" in _run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"])


def usb_capture(asound: pathlib.Path):
    """arecord on the first USB card with a capture device, resampled to 16 kHz by ALSA's
    plug (speex, /etc/asound.conf from device/install.sh). None if there is none."""
    for card in sorted(asound.glob("card[0-9]*")):
        if (card / "usbid").exists() and any(card.glob("pcm*c")):
            cid = (card / "id").read_text().strip()
            return ["arecord", "-q", "-D", f"plughw:CARD={cid},DEV=0", "-t", "raw",
                    "-f", "S16_LE", "-r", "16000", "-c", "1"]
    return None


# ── the button, watched ─────────────────────────────────────────────────────

class Watched:
    """The speaker's button, checked every CHECK_S for the speaker and the mic. A
    button read that fails (its input device went with the speaker) is a lost speaker."""

    def __init__(self, button, board, mac, mic, clock=time.monotonic):
        self.button, self.board, self.mac, self.mic, self.clock = button, board, mac, mic, clock
        self.mode = button.mode
        self._checked = clock()

    def _check(self):
        if self.clock() - self._checked < CHECK_S:
            return
        self._checked = self.clock()
        if self.board.connected_speaker() != self.mac:
            raise SpeakerLost()
        if self.mic is not None and not self.mic.alive():
            raise MicLost()

    def poll(self, timeout):
        self._check()
        try:
            return self.button.poll(timeout)
        except OSError:
            raise SpeakerLost() from None

    def drain(self):
        try:
            self.button.drain()
        except OSError:
            raise SpeakerLost() from None


class LiveMic:
    """voice.listen.Mic, and whether its capture is still running (a USB mic pulled out
    ends arecord)."""

    def __init__(self, cmd):
        from voice import listen
        self._mic = listen.Mic(cmd)

    def alive(self) -> bool:
        return self._mic.proc.poll() is None

    def start(self, sink, pre_roll=True):
        self._mic.start(sink, pre_roll)

    def stop(self):
        self._mic.stop()

    def close(self):
        self._mic.close()


# ── power-on to power-off ───────────────────────────────────────────────────

class Pocket:
    def __init__(self, board, session, hearing, speaker, out, make_mic=LiveMic,
                 clock=time.monotonic, sleep=time.sleep, say_log=print):
        self.board, self.session, self.hearing, self.speaker = board, session, hearing, speaker
        self.out, self.make_mic, self.clock, self.sleep = pathlib.Path(out), make_mic, clock, sleep
        self.print = say_log
        self.mac = None
        self.ready_at = None        # seconds since power-on when the start-up line was said
        self._started = False

    def event(self, name: str, **kw) -> None:
        rec = {"event": name, "time": _now(), "uptime_s": round(self.board.uptime(), 2), **kw}
        with (self.out / "autostart.jsonl").open("a") as f:
            f.write(json.dumps(rec) + "\n")
        self.print(f"[{rec['uptime_s']:.1f}s] {name} {kw or ''}", flush=True)

    def say(self, text: str) -> None:
        self.speaker.say(text)

    # the speaker

    def wait_speaker(self) -> str:
        while True:
            mac = self.board.connected_speaker()
            if mac:
                return mac
            for mac in self.board.paired_speakers():
                self.board.connect(mac)
                if self.board.connected_speaker():
                    break
            else:
                self.sleep(SPEAKER_RETRY_S)

    def on_speaker(self, mac: str) -> None:
        self.mac = mac
        self.speaker.device = f"bluealsa:DEV={mac},PROFILE=a2dp"
        self.sleep(SETTLE_S)
        if not self._started:
            self._started = True
            self.ready_at = round(self.board.uptime(), 2)
            self.event("ready", speaker=mac, line="start-up")
            self.say(self.session.announce.text)
        else:
            self.event("ready", speaker=mac, line="reconnected")
            self.say(READY)

    # the mic and the button

    def wait_mic(self, button):
        """The mic's capture command, saying NO_MIC once, and again on a press."""
        cmd = self.board.mic()
        if cmd:
            return cmd
        self.event("no_mic")
        self.say(NO_MIC)
        watched = Watched(button, self.board, self.mac, None, self.clock) if button is not None else None
        while True:
            if watched is not None:
                if watched.poll(MIC_RETRY_S) == "down":
                    self.say(NO_MIC)
            else:
                if self.board.connected_speaker() != self.mac:
                    raise SpeakerLost()
                self.sleep(MIC_RETRY_S)
            cmd = self.board.mic()
            if cmd:
                self.event("mic_found", capture=" ".join(cmd))
                self.say(READY)
                return cmd

    def find_button(self):
        end = self.clock() + BUTTON_WAIT_S
        said = False
        while True:
            button, name = self.board.button()
            if button is not None:
                return button
            if self.board.connected_speaker() != self.mac:
                raise SpeakerLost()
            if self.clock() >= end and not said:
                self.event("no_button")
                self.say(NO_BUTTON)
                said = True
            self.sleep(1.0)

    # the session

    def connected(self) -> None:
        """One connection of the speaker: until it drops (SpeakerLost)."""
        button = self.find_button()
        while True:
            cmd = self.wait_mic(button)
            mic = self.make_mic(cmd)
            try:
                d = dev.Device(self.session, self.hearing, mic,
                               Watched(button, self.board, self.mac, mic, self.clock),
                               self.speaker, self.out)
                while True:
                    rec = d.turn()
                    self.print(f"[{rec['n']}] heard {rec['heard']!r} -> {rec['written']}", flush=True)
            except MicLost:
                self.event("mic_lost")
            finally:
                mic.close()

    def run(self, forever=True) -> None:
        while True:
            mac = self.wait_speaker()
            self.on_speaker(mac)
            try:
                self.connected()
            except SpeakerLost:
                self.event("speaker_lost", speaker=self.mac)
            if not forever:
                return


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def stamped_log(path, board):
    """The dose log (fsynced per line), each line with this power-on's boot id and the
    seconds since power-on: the clock may be wrong without the network."""
    write, bid = jsonl_log(path), board.boot_id()

    def log(record: dict) -> None:
        write({**record, "boot_id": bid, "uptime_s": round(board.uptime(), 2)})
    return log


def main() -> None:
    board = Board()
    t0 = board.uptime()
    out = ROOT / "bench-out" / (datetime.datetime.now().strftime("autostart-%Y%m%d-%H%M%S-")
                                + board.boot_id()[:8])
    out.mkdir(parents=True, exist_ok=True)
    log = stamped_log(out / "doses.jsonl", board)
    log({"event": "power_on", "time": _now(), "clock_synchronized": board.clock_synchronized()})
    import vosk
    from voice.hear import Hearing
    from voice.speak import Speaker
    vosk.SetLogLevel(-1)
    session = boot(ROOT / "bank", log=log)
    hearing = Hearing(vosk.Model(str(dev.MODEL)), json.loads(dev.GRAMMAR.read_text()), session.vocab)
    speaker = Speaker(dev.PIPER, device="null")
    pocket = Pocket(board, session, hearing, speaker, out)
    pocket.event("loaded", load_s=round(board.uptime() - t0, 2))
    pocket.run()


if __name__ == "__main__":
    main()
