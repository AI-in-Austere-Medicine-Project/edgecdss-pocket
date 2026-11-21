"""Speech out, for the device: Piper, one sentence at a time, to the speaker.

Each sentence is played while the next is made, so a long step starts at once. A press
of the button stops it (`interrupted`). Audio goes through sox (to 44.1 kHz stereo: the
JBL plays nothing on bluez-alsa's 16 kHz mono A2DP link, device/RADXA.md) into aplay.

  POCKET_PLAY   the aplay device; default the connected A2DP speaker or headset, else
                ALSA's default. "null" plays nowhere (a dry run).
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


def play_device() -> str:
    if os.getenv("POCKET_PLAY"):
        return os.environ["POCKET_PLAY"]
    if shutil.which("bluealsa-cli"):
        out = subprocess.run(["bluealsa-cli", "list-pcms"], capture_output=True, text=True).stdout
        for line in out.split():
            if line.endswith("/a2dpsrc/sink"):
                mac = line.split("/")[4][4:].replace("_", ":")
                return f"bluealsa:DEV={mac},PROFILE=a2dp"
    return "default"


def tone(rate: int, freq: float, seconds: float) -> bytes:
    n = int(rate * seconds)
    fade = max(1, int(rate * 0.01))
    return b"".join(struct.pack("<h", int(12000 * min(1, i / fade, (n - i) / fade)
                                          * math.sin(2 * math.pi * freq * i / rate)))
                    for i in range(n))


class Speaker:
    def __init__(self, onnx, device=None):
        from piper import PiperVoice
        self.voice = PiperVoice.load(str(onnx))
        self.rate = self.voice.config.sample_rate
        self.device = device or play_device()

    def _open(self):
        sox = subprocess.Popen(["sox", "-q", "-t", "raw", "-r", str(self.rate), "-e", "signed", "-b", "16",
                                "-c", "1", "-", "-t", "raw", "-r", str(OUT_RATE), "-c", "2", "-"],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        play = subprocess.Popen(["aplay", "-q", "-D", self.device, "-t", "raw", "-f", "S16_LE",
                                 "-r", str(OUT_RATE), "-c", "2"], stdin=sox.stdout,
                                stderr=subprocess.DEVNULL)
        sox.stdout.close()
        return sox, play

    def _play(self, chunks, interrupted) -> bool:
        """True if it played to the end; False if `interrupted()` stopped it."""
        sox, play = self._open()
        try:
            sox.stdin.write(bytes(int(self.rate * LEAD_S) * 2))
            for pcm in chunks:
                if interrupted():
                    return False
                sox.stdin.write(pcm)
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
