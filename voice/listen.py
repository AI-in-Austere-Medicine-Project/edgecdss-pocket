"""Microphone and push-to-talk, for the device.

The headset mic runs all the time (a Bluetooth headset takes a second or more to switch
into its mic profile, so it is opened once, at start). Speech between press and release,
plus a short pre-roll, goes to Vosk as it arrives; at release only the tail is left to
decode. Release-to-parse is timed from the moment the release event is read.
"""
import collections
import os
import select
import shutil
import struct
import subprocess
import sys
import threading
import time

RATE = 16000
CHUNK = 640                 # 20 ms of 16-bit mono
PRE_ROLL_CHUNKS = 15        # 300 ms before the press

# Media keys a headset button can send over AVRCP (linux/input-event-codes.h).
BUTTON_KEYS = {164: "PLAYPAUSE", 200: "PLAYCD", 201: "PAUSECD", 207: "PLAY", 119: "PAUSE",
               226: "MEDIA", 169: "PHONE", 163: "NEXTSONG", 165: "PREVIOUSSONG", 166: "STOPCD"}
EV_KEY = 1
_EVENT = struct.Struct("llHHi")


def bluealsa_headset():
    """The MAC of a headset whose HFP/HSP mic bluez-alsa offers, or None."""
    if not shutil.which("bluealsa-cli"):
        return None
    out = subprocess.run(["bluealsa-cli", "list-pcms"], capture_output=True, text=True).stdout
    for line in out.split():
        if line.endswith(("/hfpag/source", "/hspag/source")):
            return line.split("/")[4][4:].replace("_", ":")
    return None


def capture_command(source=None) -> list:
    """Raw 16 kHz mono s16le on stdout. POCKET_CAPTURE overrides (split on spaces).
    On the device: bluez-alsa's SCO PCM for the headset (mSBC is 16 kHz already)."""
    if os.getenv("POCKET_CAPTURE"):
        return os.environ["POCKET_CAPTURE"].split()
    mac = source or bluealsa_headset()
    if mac and shutil.which("arecord"):
        return ["arecord", "-q", "-D", f"bluealsa:DEV={mac},PROFILE=sco", "-t", "raw",
                "-f", "S16_LE", "-r", str(RATE), "-c", "1"]
    if shutil.which("parec"):
        cmd = ["parec", "--raw", "--format=s16le", f"--rate={RATE}", "--channels=1",
               "--latency-msec=20"]
        return cmd
    if shutil.which("pw-record"):
        return ["pw-record", "--rate", str(RATE), "--channels", "1", "--format", "s16", "-"]
    return ["arecord", "-q", "-t", "raw", "-f", "S16_LE", "-r", str(RATE), "-c", "1"]


class Mic:
    def __init__(self, cmd):
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.pre = collections.deque(maxlen=PRE_ROLL_CHUNKS)
        self.sink = None            # a callable while the button is held
        self.lock = threading.Lock()
        self.alive = True
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while self.alive:
            data = self.proc.stdout.read(CHUNK)
            if not data:
                break
            with self.lock:
                if self.sink:
                    self.sink(data)
                else:
                    self.pre.append(data)

    def start(self, sink):
        with self.lock:
            for d in self.pre:
                sink(d)
            self.pre.clear()
            self.sink = sink

    def stop(self):
        with self.lock:
            self.sink = None

    def close(self):
        self.alive = False
        self.proc.terminate()


def find_button(name_hint=None):
    """The /dev/input event node of the headset's media keys: the device named
    POCKET_PTT_NAME, else one whose name says AVRCP."""
    hint = (name_hint or os.getenv("POCKET_PTT_NAME") or "AVRCP").lower()
    block = {}
    with open("/proc/bus/input/devices") as f:
        for line in f.read().split("\n"):
            if line.startswith("N: Name="):
                block["name"] = line[8:].strip('"')
            elif line.startswith("H: Handlers="):
                block["event"] = next((h for h in line.split("=")[1].split() if h.startswith("event")), None)
            elif not line.strip():
                if hint in block.get("name", "").lower() and block.get("event"):
                    return "/dev/input/" + block["event"], block["name"]
                block = {}
    return None, None


class Button:
    """Press and release of a headset button. mode "hold": key down starts, key up
    stops. mode "toggle" (headsets that send down and up together on one press): one
    press starts, the next stops."""

    def __init__(self, path, mode="hold"):
        self.fd = os.open(path, os.O_RDONLY)
        self.mode = mode

    def _key(self):
        while True:
            data = os.read(self.fd, _EVENT.size)
            _s, _us, typ, code, value = _EVENT.unpack(data)
            if typ == EV_KEY and code in BUTTON_KEYS and value in (0, 1):
                return value, time.monotonic(), BUTTON_KEYS[code]

    def drain(self):
        while select.select([self.fd], [], [], 0)[0]:
            os.read(self.fd, _EVENT.size)

    def press(self):
        while True:
            value, t, key = self._key()
            if value == 1:
                return t, key

    def release(self):
        while True:
            value, t, key = self._key()
            if (self.mode == "hold" and value == 0) or (self.mode == "toggle" and value == 1):
                return t, key


class EnterKey:
    """Bench fallback: Enter starts, Enter stops."""

    def drain(self):
        pass

    def press(self):
        sys.stdin.readline()
        return time.monotonic(), "ENTER"

    def release(self):
        sys.stdin.readline()
        return time.monotonic(), "ENTER"
