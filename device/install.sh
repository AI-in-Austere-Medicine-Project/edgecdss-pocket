#!/usr/bin/env bash
# Pocket on a fresh Radxa ZERO 3W (Radxa OS, Debian 12), in one command (owner, 2026-11-21):
#
#   git clone https://github.com/AI-in-Austere-Medicine-Project/edgecdss-pocket ~/edgecdss-pocket \
#     && bash ~/edgecdss-pocket/device/install.sh [--speaker MAC]
#
# Needs the network and sudo while it runs; Pocket needs neither afterwards. Safe to run
# again: each step checks what is already there.
#   1. packages; bluez-alsa 4.3.1 built from source (mSBC, bluealsa-cli; device/RADXA.md)
#   2. the Python venv (vosk, piper-tts) and the models, checked by sha256
#   3. the speaker: --speaker MAC pairs and trusts it (put it in pairing mode first);
#      without it, every paired speaker is trusted, so it may connect to the board itself
#   4. power can be cut at any time: no swap on the card, the journal in RAM, noatime,
#      no package updates in the background (device/RADXA.md, "Power-up and power-off")
#   5. pocket.service: starts at boot, restarts if it stops
set -euo pipefail

SPEAKER=""
while [ $# -gt 0 ]; do
  case "$1" in
    --speaker) SPEAKER="$2"; shift 2 ;;
    *) echo "usage: $0 [--speaker MAC]" >&2; exit 2 ;;
  esac
done

REPO="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="$(id -un)"
HOME_DIR="$HOME"
VENV="$HOME_DIR/pocket-venv"
[ "$REPO" = "$HOME_DIR/edgecdss-pocket" ] || { echo "STOP: the repo must be at $HOME_DIR/edgecdss-pocket (it is at $REPO)" >&2; exit 1; }
cd "$REPO"

VOSK_MODEL=vosk-model-small-en-us-0.15
VOSK_ZIP_SHA256=30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498
PIPER_VOICE=en_US-lessac-low
PIPER_URL=https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/low
PIPER_ONNX_SHA256=f7d01dde371555732c4c314111ac79672b1a5ce2fc19266ab42178fd8df7f375
BLUEZ_ALSA_TAG=v4.3.1

echo "== 1. packages"
sudo apt-get update -q
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q \
  bluez alsa-utils libasound2-plugins sox git curl unzip python3-venv python3-pip \
  build-essential autoconf automake libtool pkg-config libasound2-dev libbluetooth-dev \
  libdbus-1-dev libglib2.0-dev libsbc-dev libspandsp-dev libreadline-dev

if ! { command -v bluealsa-cli >/dev/null && bluealsa --version 2>/dev/null | grep -q "${BLUEZ_ALSA_TAG}"; }; then
  echo "== 1b. bluez-alsa ${BLUEZ_ALSA_TAG} from source"
  # Debian's bluez-alsa 4.0.0 has no mSBC and no bluealsa-cli (device/RADXA.md).
  sudo apt-get remove -y -q bluez-alsa-utils libasound2-plugin-bluez 2>/dev/null || true
  mkdir -p "$HOME_DIR/src"
  [ -d "$HOME_DIR/src/bluez-alsa" ] || git clone -q https://github.com/arkq/bluez-alsa "$HOME_DIR/src/bluez-alsa"
  (cd "$HOME_DIR/src/bluez-alsa" && git fetch -q --tags && git checkout -q "$BLUEZ_ALSA_TAG" \
    && autoreconf --install --force >/dev/null && mkdir -p build && cd build \
    && ../configure -q --prefix=/usr --sysconfdir=/etc --localstatedir=/var --enable-msbc \
         --enable-cli --enable-aplay --enable-systemd \
         --with-alsaplugindir="/usr/lib/$(gcc -dumpmachine)/alsa-lib" \
    && make -s -j"$(nproc)" && sudo make -s install)
fi
sudo mkdir -p /etc/systemd/system/bluealsa.service.d
sudo tee /etc/systemd/system/bluealsa.service.d/pocket-hfp.conf >/dev/null <<'EOF'
[Service]
ExecStart=
ExecStart=/usr/bin/bluealsa -S --a2dp-force-audio-cd -p a2dp-source -p a2dp-sink -p hfp-ag
EOF
# The USB mic is resampled to 16 kHz by ALSA's plug: speex, not the default linear.
sudo tee /etc/asound.conf >/dev/null <<'EOF'
# EdgeCDSS Pocket (device/install.sh): resample with speex
defaults.pcm.rate_converter "speexrate_medium"
EOF
sudo usermod -aG audio,bluetooth,input "$USER_NAME"
sudo sed -i 's/^#\?AutoEnable=.*/AutoEnable=true/' /etc/bluetooth/main.conf
sudo systemctl daemon-reload
sudo systemctl enable --now bluetooth bluealsa
sudo systemctl restart bluealsa

echo "== 2. python and the models"
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
"$VENV/bin/python" -c "import vosk, piper" 2>/dev/null \
  || "$VENV/bin/python" -m pip install -q vosk==0.3.45 piper-tts==1.8.0
mkdir -p models/piper
if [ ! -d "models/$VOSK_MODEL" ]; then
  curl -sSL -o "models/$VOSK_MODEL.zip" "https://alphacephei.com/vosk/models/$VOSK_MODEL.zip"
  echo "$VOSK_ZIP_SHA256  models/$VOSK_MODEL.zip" | sha256sum -c --quiet -
  (cd models && unzip -q "$VOSK_MODEL.zip" && rm "$VOSK_MODEL.zip")
fi
ONNX="models/piper/$PIPER_VOICE.onnx"
if ! echo "$PIPER_ONNX_SHA256  $ONNX" | sha256sum -c --quiet - 2>/dev/null; then
  curl -sSL -o "$ONNX" "$PIPER_URL/$PIPER_VOICE.onnx"
  echo "$PIPER_ONNX_SHA256  $ONNX" | sha256sum -c --quiet -
fi
[ -f "$ONNX.json" ] || curl -sSL -o "$ONNX.json" "$PIPER_URL/$PIPER_VOICE.onnx.json"
"$VENV/bin/python" - "models/$VOSK_MODEL" <<'PYEOF'
import json, pathlib, sys
from engine.bank import load_bank
from voice.grammar import model_id
g = json.loads(pathlib.Path("grammar/vosk_grammar.json").read_text())
assert g["model_am_sha256"] == model_id(sys.argv[1])["model_am_sha256"], "grammar is for another model"
assert g["bank_hash"] == load_bank("bank").hash, "grammar is for another bank"
print("grammar ok for this model and bank")
PYEOF

echo "== 3. the speaker"
bluetoothctl power on >/dev/null
if [ -n "$SPEAKER" ]; then
  if ! bluetoothctl info "$SPEAKER" 2>/dev/null | grep -q "Paired: yes"; then
    echo "pairing $SPEAKER: it must be in pairing mode now"
    timeout 30 bluetoothctl --timeout 25 scan on >/dev/null || true
    bluetoothctl pair "$SPEAKER"
  fi
  bluetoothctl trust "$SPEAKER"
fi
for mac in $(bluetoothctl devices Paired | awk '$1 == "Device" {print $2}'); do
  if bluetoothctl info "$mac" | grep -q "Audio Sink"; then bluetoothctl trust "$mac" >/dev/null; echo "speaker: $mac"; fi
done

echo "== 4. power can be cut at any time"
if grep -qE '^[^#].*\sswap\s' /etc/fstab; then
  sudo swapoff -a || true
  sudo sed -i -E 's|^([^#].*\sswap\s.*)$|# pocket: no swap on the card # \1|' /etc/fstab
fi
if ! awk '$2 == "/" {print $4}' /etc/fstab | grep -q noatime; then
  sudo sed -i -E 's|^(\S+\s+/\s+ext4\s+)(\S+)|\1\2,noatime|' /etc/fstab
fi
sudo mkdir -p /etc/systemd/journald.conf.d
sudo tee /etc/systemd/journald.conf.d/pocket.conf >/dev/null <<'EOF'
# EdgeCDSS Pocket: the journal in RAM, so the card is written less (power can be cut).
[Journal]
Storage=volatile
RuntimeMaxUse=48M
EOF
sudo systemctl restart systemd-journald
for t in apt-daily.timer apt-daily-upgrade.timer man-db.timer; do
  sudo systemctl disable --now "$t" 2>/dev/null || true
done

echo "== 4b. Wi-Fi joins at power-up (for upkeep over Tailscale; Pocket itself needs no network)"
# NetworkManager on this board joins the saved (hidden) network only once a scan has seen
# it: 47 s, 3 min, or never. The keeper asks it to join every 30 s while Wi-Fi is on and not
# connected; Wi-Fi turned off on purpose stays off.
sudo install -m 755 device/pocket-wifi-up /usr/local/sbin/pocket-wifi-up
sudo install -m 644 device/pocket-wifi-up.service device/pocket-wifi-up.timer /etc/systemd/system/
sudo systemctl disable --now pocket-test-wifi-on.timer 2>/dev/null || true      # the no-network test's, if left
sudo rm -f /etc/systemd/system/pocket-test-wifi-on.timer /etc/systemd/system/pocket-test-wifi-on.service
sudo systemctl daemon-reload
sudo systemctl enable --now pocket-wifi-up.timer

echo "== 5. pocket.service"
sed -e "s|@USER@|$USER_NAME|g" -e "s|@HOME@|$HOME_DIR|g" device/pocket.service \
  | sudo tee /etc/systemd/system/pocket.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable pocket.service
sudo systemctl restart pocket.service
sleep 2
systemctl is-active pocket.service
echo "done: Pocket starts at power-up. Its log: journalctl -u pocket -f; its files: $REPO/bench-out/autostart-*"
