# Radxa Zero: the primary board

The Pi Zero 2 W is below the memory floor ([docs/BOARDS.md](../docs/BOARDS.md)). These
steps match the Pi's, with the differences called out. **Nothing here has run on a Radxa
yet.** The image choice is from published reports, and step 5 is the check that decides it.

## Which board, which image

"Radxa Zero" is three different boards. The markings on the board say which one:

| Board | SoC | Wireless | Image | Why |
|---|---|---|---|---|
| **ZERO 3W** (current module, D8) | Rockchip RK3566 | AIC8800DS2 (Wi-Fi 6, BT 5.4) | **Radxa OS** (Debian 12 bookworm, rsdk b1 or later) | Radxa added the D8 module in its own image (b6 changelog). Reports of Armbian on the AIC8800 say Bluetooth did not come up, or came up only with a manual `hciattach` on `/dev/ttyS1` after every boot. Reports say it works on Radxa's image. |
| **ZERO 3W** (early, AP6212) / **ZERO 3E** (no wireless) | RK3566 | AP6212 (BCM43430) / none | Armbian Debian 13 trixie minimal, else Radxa OS | Broadcom Bluetooth over UART is mainline. The 3E needs a USB Bluetooth adapter. |
| **ZERO** (original) | Amlogic S905Y2 | AP6256 (BCM43456) | **Armbian** Debian 13 trixie minimal (mainline kernel) | Radxa's own image for this board is old (Debian 11). postmarketOS and Armbian list its Bluetooth as working on mainline. |

None of the reports found covers **HFP/SCO headset audio** (the mic) on any of these
boards. Most cover Bluetooth pairing, and some cover A2DP. Step 5 is that test, run before
anything else is installed. If HFP fails on the chosen image, try the other image before
giving up on the board.

Radxa OS for the ZERO 3W now ships the KDE desktop image only (Radxa: "For most systems,
Radxa now only supports the Debian Desktop image"; the b6 CLI image had a boot bug). Boot it
to the console (step 2) so the desktop and its PipeWire don't hold memory or the headset.

RAM: the floor is Vosk, Piper and the engine (about 300 MB together on the Pi) with at
least 100 MB free. Every Radxa Zero variant has 1 GB or more, which clears it with room
to spare. Step 8 measures it.

## Steps

1. **Flash.** Write the image to the microSD (or eMMC through the board's USB boot mode).
   Use `xz -dc IMAGE.img.xz | sudo dd of=/dev/sdX bs=4M conv=fsync status=progress`, or Radxa's
   or Armbian's own tool. First boot: user `andrew`, hostname `pocket`. Armbian asks for both
   on the serial or HDMI console. On Radxa OS, rename the default user (`radxa`) to `andrew`
   or create `andrew` with sudo, and set the hostname with `hostnamectl set-hostname pocket`.
2. **Console only** (Radxa OS desktop image): `sudo systemctl set-default multi-user.target`,
   then reboot.
3. **Network and access** (as on the Pi): connect Wi-Fi with `nmtui`, install Tailscale
   (`curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up`), add the SSH key
   to `~/.ssh/authorized_keys`. Make the journal persistent so a failure leaves a log:
   `sudo mkdir -p /var/log/journal && sudo systemctl restart systemd-journald`. On the Pi it
   was volatile, and the crash's log was lost.
4. **Bluetooth up.** `sudo apt install bluez bluez-alsa-utils alsa-utils sox git python3-venv`.
   - Armbian on an AIC8800: if `bluetoothctl list` shows no controller, check `rfkill list`
     (one report found it soft-blocked after first boot: `sudo rfkill unblock bluetooth`).
   - Radxa OS: the image brings the controller up itself.
5. **Headset mic: the gate.** Pair TK-01 (98:D3:31:03:10:42): `bluetoothctl`, then
   `power on`, `scan on`, `pair`, `trust`, `connect`. Then:
   - The repo's bluealsa drop-in adds `hfp-ag` and `hsp-ag`; `device/setup_voice.sh` writes it.
     Bring it in early: `git clone` the repo, run the script once (it is safe to run again),
     reconnect the headset.
   - `bluealsa-cli list-pcms` must show `.../dev_98_D3_31_03_10_42/hfpag/source`.
   - Record five seconds and play them back:
     `arecord -D bluealsa:DEV=98:D3:31:03:10:42,PROFILE=sco -f S16_LE -r 16000 -c 1 -d 5 /tmp/t.wav`,
     then copy it off and listen. Speech must be clear at 16 kHz (mSBC). 8 kHz CVSD means the
     image or controller lacks wide-band speech: record it as a finding.
   - If PipeWire is running (desktop image), it and bluealsa fight over the headset. Keep
     bluealsa: `systemctl --user mask --now wireplumber pipewire pipewire-pulse`.
6. **Button.** `grep -A4 AVRCP /proc/bus/input/devices` shows the headset's event node.
   `andrew` must be in group `input` (`sudo usermod -aG input andrew`, then log in again).
   Hold the button for 2 s, then press it once quickly, while reading the node, to choose
   `--mode hold` or `--mode toggle`.
7. **Voice.** `bash device/setup_voice.sh` creates the venv `~/pocket-venv`, installs vosk
   0.3.45, downloads the model with its checksum check, and checks the committed grammar
   against this model and bank. For Piper: `~/pocket-venv/bin/pip install piper-tts`, and
   en_US-lessac-low into `models/piper/` (sha256 of the .onnx:
   `f7d01dde371555732c4c314111ac79672b1a5ce2fc19266ab42178fd8df7f375`).
8. **Memory.** `bash device/memory.sh` adds the 512 MB swap file under the image's zram and
   writes pocket.slice. Then
   `~/pocket-venv/bin/python -m voice.tools.memprobe models/vosk-model-small-en-us-0.15 --mic --piper models/piper/en_US-lessac-low.onnx --json bench-out/mem.json`.
   Record the table in docs/BOARDS.md. Pass: at least 100 MB available at every stage and
   nothing in swap.
9. **Drug-name gate, then the spoken replay** (as planned on the Pi):
   - `~/pocket-venv/bin/python -m voice.bench models/vosk-model-small-en-us-0.15 --names --mode <m>`:
     the owner says the 25 names and 6 medic forms, and each must be heard as its drug.
   - Then the replay without `--names`: 50 phrases, WER and release-to-parse latency.

## What changes from the Pi

- **Memory.** The memory floor is met on a 1 GB or larger board. The memory controller is
  normally on (Armbian and Radxa OS do not disable it). `device/memory.sh` then reports
  "memory controller delegated", and the pocket.slice ceiling holds. Its defaults (high 260M,
  max 300M, swap 96M) were placeholders sized for the Pi. Set them from step 8
  (`POCKET_MEMORY_MAX=... bash device/memory.sh`): about 1.5× the measured peak.
- **Swap.** Armbian sets up zram with `armbian-zram-config`; Radxa OS's setup has not been
  checked. The swap file goes under whichever is there, as on the Pi.
- **Bluetooth.** The controller is a different chip (AIC8800 or Broadcom, not the Pi's
  CYW43436). Bring-up is image-specific (step 4), and wide-band speech (mSBC) must be
  rechecked (step 5).
- **Audio stack.** Same bluez-alsa path. `voice/listen.py` picks the bluealsa SCO PCM first,
  so no code change is needed. On the desktop image, mask PipeWire (step 5) rather than
  switch the code to `pw-record`.
- **Python.** Debian 12 (Radxa OS) has Python 3.11 and Debian 13 (Armbian trixie) has 3.13.
  vosk 0.3.45 and piper-tts have aarch64 wheels for both. The engine needs nothing newer
  than 3.11. Run the tests on the board once:
  `~/pocket-venv/bin/pip install pytest && ~/pocket-venv/bin/python -m pytest -q`.
- **Unchanged.** The model, grammar, spellings, bank, engine, bench and setup scripts. The
  committed grammar is checked against the model's own `am/final.mdl` hash, so it is valid
  on any board running the same model.

## Sources

- Radxa ZERO 3 images and the b6 notes (D8 / AIC8800DS2 support, desktop-only):
  https://github.com/radxa-build/radxa-zero3/releases
- AIC8800 Bluetooth on Armbian, manual `hciattach`; works on Radxa bookworm:
  https://forum.armbian.com/topic/50389-bluetooth-not-working-with-armbian-noble-2404-2025-03-07/
- ZERO 3W Bluetooth reports (rfkill soft block; Radxa b6 working; /dev/ttyS1):
  https://dietpi.com/forum/t/radxa-zero-3w-bluetooth-not-working/20555 and
  https://forum.radxa.com/t/bluetooth-not-working-zero-3w-official-os/24072
- ZERO 3W wireless module (D8, AIC8800, earlier AP6212):
  https://www.cnx-software.com/2023/12/08/radxa-zero-3w-sbc-rockchip-rk3566-8gb-ram-wifi6-raspberry-pi-zero-2-w-form-factor/
- Original Radxa Zero on mainline (Bluetooth working, AP6256): https://wiki.postmarketos.org/wiki/Radxa_Zero_(radxa-zero)
  and Armbian: https://www.armbian.com/radxa-zero/
