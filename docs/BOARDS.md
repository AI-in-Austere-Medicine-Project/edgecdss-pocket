# Boards

| Board | RAM | Status |
|---|---|---|
| Radxa Zero (model to be confirmed from its markings) | ≥ 1 GB | **Primary** (owner decision, 2026-11-09). Setup: [device/RADXA.md](../device/RADXA.md) |
| Raspberry Pi Zero 2 W | 512 MB (415 MB to Linux) | **Below the memory floor.** Not a target. Record below. |

## Raspberry Pi Zero 2 W: below the memory floor

The floor: Vosk listening, Piper loaded, and the engine resident together, with at least
100 MB free (MemAvailable) on the board. The Zero 2 W does not reach it.

Measured 2026-11-09 with `voice/tools/memprobe.py` on the Pi (Debian 13 trixie, Raspberry
Pi OS kernel, Python 3.13, vosk 0.3.45, piper-tts 1.8.0). Everything is in one process, the
same way the pocket runs. Audio was a recorded 16 kHz clip: the headset had not reconnected
after a reboot, so the arecord capture process (a few MB) is not counted. Swap was zram
(415 MB) with a 512 MB file under it (`device/memory.sh`). The table shows the third of three
runs; the others agree within the noise of swap.

| Stage | Resident | In swap | Available on the Pi |
|---|---|---|---|
| Python alone | 12 MB | 0 | 258 MB |
| Engine (bank, vocabulary, session) | 20 MB | 0 | 250 MB |
| Vosk model (vosk-model-small-en-us-0.15) | 157 MB | 0 | 123 MB |
| Vosk listening (both recognisers, fed audio) | 163 MB | 0 | 119 MB |
| Piper loaded (en_US-lessac-low, 63 MB) | 104 MB | 168 MB | 89 MB |
| Piper spoke one dose | 133 MB | 167 MB | 77 MB |
| Vosk listening again | 140 MB | 161 MB | 66 MB |

- With all of it loaded, the process holds about 300 MB (resident plus swapped) against
  415 MB of RAM. About 165 MB lives in swap, and 66–89 MB is free.
- **Speed.** Before Piper, Vosk finished an utterance 170 ms after the end of the audio.
  After Piper had run, decoding 1.26 s of audio took 1.43 s, plus 237 ms to finish. That is
  slower than real time: the Vosk pages come back from swap as they are needed.
- Piper took 3.4–5.6 s to say "Ketamine. Twenty milligrams. Four millilitres of the dilution."
- **Memory limit.** The firmware puts `cgroup_disable=memory` on the kernel command line of
  low-RAM Pis, so a cgroup memory ceiling (`device/memory.sh`, pocket.slice) is not
  enforced. The owner ruled not to enable it on this board.
- **Lost log.** During `setup_voice.sh` (which then loaded the model a second time to
  generate the grammar) the board stopped answering, and it later rebooted. The journal is
  volatile (`Storage=volatile`), so the previous boot's log was lost and an OOM kill can be
  neither confirmed nor ruled out. The hardware watchdog (1 min) resets a board that stops
  responding.

Raw probe output stays on the Pi: `~/edgecdss-pocket/bench-out/mem-wav-{1,2,3}.json`.
