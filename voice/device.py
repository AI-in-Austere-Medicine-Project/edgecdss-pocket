"""The device: push-to-talk, the session, speech out. Drugs and procedure steps by voice.

  python3 -m voice.device [--mode toggle|hold] [--enter] [--out DIR]
  python3 -m voice.device --typed     type what you would say; the answer is spoken

Press, hear the beep, speak; release ("hold") or press again ("toggle"; the JBL Clip 3).
What was heard goes to the same Session the typed path uses, as heard (spoken=True: a
confused pair asks "X or Y?" first), and its answer is spoken in the spoken form. A press
while it speaks stops it and listens. A read-back not confirmed within 30 s is cancelled
aloud, once, so a later "yes" never confirms an old dose.

Everything goes to DIR (default bench-out/device-<time>/): doses.jsonl (the start-up line,
then each dose: the session's log, rule 3), heard.jsonl (one line per utterance: what was
heard, by which decoder, the answer in both forms, timings) and NNN.wav.

With no POCKET_CAPTURE the mic is the connected headset's own (the JBL's, 8 kHz), and
speech then goes back over its call link, since its A2DP link stalls while the mic is open.

  POCKET_CAPTURE  the capture command (voice/listen.py); POCKET_PLAY the aplay device
  (voice/speak.py); POCKET_PTT_NAME the button's input device name.
"""
import argparse
import datetime
import json
import os
import pathlib
import time
import wave

from engine.session import boot, jsonl_log

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODEL = ROOT / "models" / "vosk-model-small-en-us-0.15"
PIPER = ROOT / "models" / "piper" / "en_US-lessac-low.onnx"
GRAMMAR = ROOT / "grammar" / "vosk_grammar.json"
RATE = 16000
NOT_HEARD = "Not heard."
MAX_LISTEN_S = 15.0     # toggle mode: a second press that never comes
IDLE_POLL_S = 0.5


class Device:
    def __init__(self, session, hearing, mic, button, speaker, out_dir, clock=time.monotonic,
                 now=None):
        self.session, self.hearing, self.mic = session, hearing, mic
        self.button, self.speaker = button, speaker
        self.out = pathlib.Path(out_dir)
        self.clock = clock
        self.now = now or (lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
        self.n = 0
        self._pressed = False     # a press that stopped speech: listen next, no wait

    # ── speech out ─────────────────────────────────────────────────────────

    def _interrupted(self) -> bool:
        if self.button.poll(0) == "down":
            self._pressed = True
            return True
        return False

    def say(self, text: str) -> bool:
        return self.speaker.say(text, self._interrupted)

    # ── one turn ───────────────────────────────────────────────────────────

    def start(self) -> None:
        self.say(self.session.announce.text)

    def wait_press(self) -> None:
        """Until the button is pressed. Meanwhile a read-back past its 30 s is cancelled
        aloud, once."""
        if self._pressed:
            self._pressed = False
            return
        while self.button.poll(IDLE_POLL_S) != "down":
            expired = self.session.expire_pending()
            if expired is not None:
                self._record({"event": "expired", "say": expired.text, "written": expired.written_text})
                self.say(expired.text)
                if self._pressed:
                    self._pressed = False
                    return

    def listen(self) -> tuple:
        """Beep, then capture until release (hold) or the next press (toggle)."""
        self.speaker.beep()
        if self.button.mode == "toggle":
            self.button.drain()       # the JBL's own key-up, and any double press
        u, pcm = self.hearing.start(), bytearray()

        def sink(d):
            pcm.extend(d)
            u.feed(d)
        self.mic.start(sink, pre_roll=False)
        end = self.clock() + MAX_LISTEN_S
        stop = "up" if self.button.mode == "hold" else "down"
        while self.clock() < end and self.button.poll(0.05) != stop:
            pass
        t_release = self.clock()
        self.mic.stop()
        heard, text, which = u.finish()
        return heard, text, which, bytes(pcm), t_release

    def turn(self) -> dict:
        self.wait_press()
        heard, text, which, pcm, t_release = self.listen()
        self.n += 1
        t_text = self.clock()
        turn = self.session.handle(text, spoken=True) if text else None
        t_turn = self.clock()
        say = turn.text if turn else NOT_HEARD
        _wav(self.out / f"{self.n:03d}.wav", pcm)
        rec = self._record({"n": self.n, "heard": heard, "decoder": which, "parsed_from": text,
                      "kind": turn.kind if turn else None, "say": say,
                      "written": turn.written_text if turn else NOT_HEARD,
                      "audio_s": round(len(pcm) / 2 / RATE, 2),
                      "release_to_text_ms": round((t_text - t_release) * 1000),
                      "release_to_turn_ms": round((t_turn - t_release) * 1000)})
        t0 = self.clock()
        done = self.say(say)
        self._record({"n": self.n, "spoke_ms": round((self.clock() - t0) * 1000), "stopped": not done})
        return rec

    def _record(self, rec: dict) -> dict:
        rec = {"time": self.now(), **rec}
        with (self.out / "heard.jsonl").open("a") as f:
            f.write(json.dumps(rec) + "\n")
        return rec


def _wav(path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)


def _lines():
    while True:
        yield input("> ")


def typed(session, speaker, lines, print=print) -> None:
    """Typed in, spoken out: each typed line goes to the session as typed (as the typed
    path does), and its answer is spoken. No mic, so no headset call link is opened and
    the speaker stays on A2DP."""
    speaker.say(session.announce.text)
    for line in lines:
        if not line.strip():
            continue
        turn = session.handle(line)
        print(turn.written_text, flush=True)
        speaker.say(turn.text)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--model", default=str(MODEL))
    ap.add_argument("--piper", default=str(PIPER))
    ap.add_argument("--bank", default=str(ROOT / "bank"))
    ap.add_argument("--out")
    ap.add_argument("--mode", choices=("hold", "toggle"), default="toggle")
    ap.add_argument("--button", help="input device name to use as push-to-talk")
    ap.add_argument("--enter", action="store_true", help="Enter key as push-to-talk (toggle)")
    ap.add_argument("--typed", action="store_true",
                    help="type what you would say; the answer is spoken (no mic)")
    a = ap.parse_args(argv)

    out = pathlib.Path(a.out or ROOT / "bench-out" / datetime.datetime.now().strftime("device-%Y%m%d-%H%M%S"))
    out.mkdir(parents=True, exist_ok=True)
    if a.typed:
        from voice.speak import Speaker
        session = boot(a.bank, log=jsonl_log(out / "doses.jsonl"))
        speaker = Speaker(a.piper)
        print(f"out: {out}\nspeaker: {speaker.device}\n{session.announce.written_text}", flush=True)
        try:
            typed(session, speaker, _lines())
        except (KeyboardInterrupt, EOFError):
            pass
        return
    import vosk
    from voice import listen
    from voice.hear import Hearing
    from voice.speak import Speaker
    vosk.SetLogLevel(-1)

    session = boot(a.bank, log=jsonl_log(out / "doses.jsonl"))
    hearing = Hearing(vosk.Model(a.model), json.loads(GRAMMAR.read_text()), session.vocab)
    headset = None if os.getenv("POCKET_CAPTURE") else listen.bluealsa_headset()
    speaker = Speaker(a.piper, headset=headset)
    if a.enter:
        button = listen.EnterKey()
    else:
        path, name = listen.find_button(a.button)
        if not path:
            raise SystemExit("No headset button found in /proc/bus/input/devices (or use --enter).")
        button = listen.Button(path, a.mode)
    capture = listen.capture_command(headset)
    mic = listen.Mic(capture)
    print(f"out: {out}\nmic: {' '.join(capture)}\nspeaker: {speaker.device}\n"
          f"button: {'Enter' if a.enter else name} ({button.mode})\n{session.announce.written_text}", flush=True)
    device = Device(session, hearing, mic, button, speaker, out)
    try:
        device.start()
        while True:
            rec = device.turn()
            print(f"[{rec['n']}] heard {rec['heard']!r} -> {rec['written']}", flush=True)
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        mic.close()


if __name__ == "__main__":
    main()
