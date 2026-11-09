"""Resident memory on the device, stage by stage, in one process as the pocket will run.

  python -m voice.tools.memprobe MODEL_DIR [--piper VOICE.onnx] [--wav FILE] [--json OUT]

Stages: python alone; the engine (bank, vocabulary, session); Vosk's model; listening
(both recognisers of one utterance, fed audio, the mic process running when --mic);
Piper's voice loaded and one dose said. At each stage: this process's resident set
(VmRSS) and its peak (VmHWM), any child (arecord) resident set, and the system's
MemAvailable and swap in use. "Free" below means MemAvailable.
"""
import argparse
import json
import pathlib
import subprocess
import sys
import time
import wave

ROOT = pathlib.Path(__file__).resolve().parents[2]
SAY = "Ketamine. Twenty milligrams. Four millilitres of the dilution."


def _status(pid="self"):
    out = {}
    for line in pathlib.Path(f"/proc/{pid}/status").read_text().splitlines():
        k, _, v = line.partition(":")
        if k in ("VmRSS", "VmHWM"):
            out[k] = int(v.split()[0]) // 1024
    return out


def _meminfo():
    m = {}
    for line in pathlib.Path("/proc/meminfo").read_text().splitlines():
        k, _, v = line.partition(":")
        m[k] = int(v.split()[0]) // 1024
    return {"total_mb": m["MemTotal"], "available_mb": m["MemAvailable"],
            "swap_used_mb": m["SwapTotal"] - m["SwapFree"], "swap_total_mb": m["SwapTotal"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--piper", help="Piper voice .onnx (its .onnx.json beside it)")
    ap.add_argument("--wav", help="16 kHz mono WAV to feed while listening")
    ap.add_argument("--mic", action="store_true", help="run the headset capture as on the device")
    ap.add_argument("--json")
    a = ap.parse_args()
    rows, children = [], []

    def stage(name):
        child = sum(_status(p.pid).get("VmRSS", 0) for p in children if p.poll() is None)
        r = {"stage": name, **{k.lower() + "_mb": v for k, v in _status().items()},
             "child_rss_mb": child, **_meminfo()}
        rows.append(r)
        print(f"{name:<28} rss {r['vmrss_mb']:>4} MB  peak {r['vmhwm_mb']:>4} MB  "
              f"child {child:>3} MB  available {r['available_mb']:>4} MB  swap {r['swap_used_mb']:>3} MB",
              flush=True)

    stage("python")
    sys.path.insert(0, str(ROOT))
    from engine.session import boot
    session = boot(ROOT / "bank")
    session.handle("ketamine for analgesia eighty kilos")
    stage("engine")

    import vosk
    vosk.SetLogLevel(-1)
    from voice.hear import Hearing
    model = vosk.Model(a.model)
    stage("vosk model")

    g = json.loads((ROOT / "grammar" / "vosk_grammar.json").read_text())
    hearing = Hearing(model, g, session.vocab)
    mic = None
    if a.mic:
        from voice import listen
        mic = listen.Mic(listen.capture_command())
        children.append(mic.proc)
        time.sleep(3)                   # the SCO link comes up
    u = hearing.start()
    if a.wav:
        with wave.open(a.wav) as w:
            data = w.readframes(w.getnframes())
    else:
        data = bytes(16000 * 2 * 4)     # four seconds of silence
    if mic:
        mic.start(u.feed)
        time.sleep(4)
        mic.stop()
    else:
        for i in range(0, len(data), 640):
            u.feed(data[i:i + 640])
    heard = u.finish()
    stage("vosk listening")

    if a.piper:
        from piper import PiperVoice
        voice = PiperVoice.load(a.piper)
        stage("piper loaded")
        t = time.monotonic()
        if hasattr(voice, "synthesize_wav"):           # piper-tts >= 1.3
            with wave.open("/dev/null", "wb") as w:
                voice.synthesize_wav(SAY, w)
        else:
            with wave.open("/dev/null", "wb") as w:
                voice.synthesize(SAY, w)
        rows.append({"piper_say_ms": round((time.monotonic() - t) * 1000)})
        stage("piper spoke")

    if mic:
        mic.close()
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps({"heard": heard, "rows": rows}, indent=1) + "\n")


if __name__ == "__main__":
    main()
