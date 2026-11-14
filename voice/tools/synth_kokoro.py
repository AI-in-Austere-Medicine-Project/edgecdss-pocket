"""Dev tool, not the device: speak a list of texts with EdgeCDSS's Kokoro voice.

  ~/pi-cloud-cdss/.venv/bin/python voice/tools/synth_kokoro.py JOBS.json OUTDIR

JOBS is [[id, text, voice, speed], ...]. Writes OUTDIR/<id>.wav at 16 kHz mono 16-bit.
Synthetic speech: for building and checking spellings only, never a measurement.
"""
import io
import json
import os
import pathlib
import subprocess
import sys
import wave

EDGECDSS = pathlib.Path(os.getenv("EDGECDSS", pathlib.Path.home() / "pi-cloud-cdss")) / "server"
sys.path.insert(0, str(EDGECDSS))
os.chdir(EDGECDSS)
os.environ.setdefault("CDSS_KOKORO_DEVICE", "cpu")
import tts  # noqa: E402

jobs, out = json.loads(pathlib.Path(sys.argv[1]).read_text()), pathlib.Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
eng = tts._engine()
for jid, text, voice, speed in jobs:
    dest = out / f"{jid}.wav"
    if dest.exists():
        continue
    samples, rate = eng.create(text, voice=voice, speed=speed, lang="en-us")
    raw = tts._wav(samples, rate)
    subprocess.run(["sox", "-q", "-t", "wav", "-", "-r", "16000", "-c", "1", "-b", "16", str(dest)],
                   input=raw, check=True)
print(len(jobs), "jobs done")
