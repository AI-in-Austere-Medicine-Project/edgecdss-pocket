"""Speech out, for the device: Piper, one sentence at a time, to the speaker.

Each sentence is played while the next is made, so a long step starts at once. A press
of the button stops it (`interrupted`). Audio goes through sox into aplay: to 44.1 kHz
stereo on A2DP (the JBL plays nothing on bluez-alsa's 16 kHz mono A2DP link), or to the
call link's rate when the headset's own mic is in use (device/RADXA.md).

  POCKET_PLAY   the aplay device; default: the headset's call link (SCO) when its mic is
                the mic, else the connected A2DP speaker, else ALSA's default. "null" plays
                nowhere (a dry run).
"""
import math
import os
import shutil
import struct
import subprocess
import time

OUT_RATE = 44100
LEAD_S = 0.15          # silence first: a Bluetooth speaker that has gone idle drops the start
BEEP = (880.0, 0.12)   # "speak now"
PIECE_S = 0.1          # a press is checked for between pieces of this much audio


def play_device(headset=None) -> str:
    """headset: the MAC whose SCO mic is open. Its A2DP link stalls while SCO is up (the
    JBL, 2026-11-21), so speech goes back over the same call link."""
    if os.getenv("POCKET_PLAY"):
        return os.environ["POCKET_PLAY"]
    if headset:
        return f"bluealsa:DEV={headset},PROFILE=sco"
    if shutil.which("bluealsa-cli"):
        out = subprocess.run(["bluealsa-cli", "list-pcms"], capture_output=True, text=True).stdout
        for line in out.split():
            if line.endswith("/a2dpsrc/sink"):
                mac = line.split("/")[4][4:].replace("_", ":")
                return f"bluealsa:DEV={mac},PROFILE=a2dp"
    return "default"


def _sco_codec(mac: str) -> str:
    path = "/org/bluealsa/hci0/dev_" + mac.replace(":", "_") + "/hfpag/sink"
    out = subprocess.run(["bluealsa-cli", "info", path], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.startswith("Selected codec:"):
            return line.split(":", 1)[1].strip()
    return "CVSD"


def out_format(device: str) -> tuple:
    """(rate, channels) to send to `device`."""
    if "PROFILE=sco" in device:
        mac = device.split("DEV=")[1].split(",")[0]
        return (16000 if _sco_codec(mac) == "mSBC" else 8000), 1
    return OUT_RATE, 2


def tone(rate: int, freq: float, seconds: float) -> bytes:
    n = int(rate * seconds)
    fade = max(1, int(rate * 0.01))
    return b"".join(struct.pack("<h", int(12000 * min(1, i / fade, (n - i) / fade)
                                          * math.sin(2 * math.pi * freq * i / rate)))
                    for i in range(n))


class Speaker:
    def __init__(self, onnx, device=None, headset=None):
        from piper import PiperVoice
        self.voice = PiperVoice.load(str(onnx))
        self.rate = self.voice.config.sample_rate
        self.device = device or play_device(headset)
        self.out_rate, self.out_channels = out_format(self.device)

    def _open(self):
        sox = subprocess.Popen(["sox", "-q", "-t", "raw", "-r", str(self.rate), "-e", "signed", "-b", "16",
                                "-c", "1", "-", "-t", "raw", "-r", str(self.out_rate), "-c", str(self.out_channels), "-"],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        play = subprocess.Popen(["aplay", "-q", "-D", self.device, "-t", "raw", "-f", "S16_LE",
                                 "-r", str(self.out_rate), "-c", str(self.out_channels)], stdin=sox.stdout,
                                stderr=subprocess.DEVNULL)
        sox.stdout.close()
        return sox, play

    def _play(self, chunks, interrupted) -> bool:
        """True if it played to the end; False if `interrupted()` stopped it."""
        sox, play = self._open()
        try:
            sox.stdin.write(bytes(int(self.rate * LEAD_S) * 2))
            step = int(self.rate * PIECE_S) * 2
            for pcm in chunks:
                # In small pieces: a write blocks while the pipe is full, so a press is
                # seen within a piece, not at the end of a long sentence (owner, 2026-11-21).
                for i in range(0, len(pcm), step):
                    if interrupted():
                        return False
                    sox.stdin.write(pcm[i:i + step])
                    sox.stdin.flush()
            sox.stdin.close()
            while play.poll() is None:
                if interrupted():
                    return False
                time.sleep(0.03)
            return True
        except BrokenPipeError:
            return True
        finally:
            for p in (sox, play):
                if p.poll() is None:
                    p.kill()
                p.wait()

    def say(self, text: str, interrupted=lambda: False) -> bool:
        return self._play((c.audio_int16_bytes for c in self.voice.synthesize(text)), interrupted)

    def beep(self) -> None:
        self._play([tone(self.rate, *BEEP)], lambda: False)
