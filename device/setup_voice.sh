#!/usr/bin/env bash
# Phase 2 on the Pi Zero 2 W: Vosk, the small English model, the grammar from the bank,
# and a report of the headset's audio and button. Safe to run again.
#   bash device/setup_voice.sh
set -euo pipefail
cd "$(dirname "$0")/.."

MODEL=vosk-model-small-en-us-0.15
MODEL_ZIP_SHA256=30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498

VENV=${POCKET_VENV:-$HOME/pocket-venv}
echo "== python and vosk ($VENV)"
[ -x "$VENV/bin/python" ] || python3 -m venv --system-site-packages "$VENV"
"$VENV/bin/python" -c "import vosk" 2>/dev/null || "$VENV/bin/python" -m pip install -q vosk==0.3.45
"$VENV/bin/python" -c "import vosk; print('vosk', vosk.__file__)"
PY="$VENV/bin/python"

echo "== model"
mkdir -p models
if [ ! -d "models/$MODEL" ]; then
  curl -sSL -o "models/$MODEL.zip" "https://alphacephei.com/vosk/models/$MODEL.zip"
  echo "$MODEL_ZIP_SHA256  models/$MODEL.zip" | sha256sum -c -
  (cd models && unzip -q "$MODEL.zip" && rm "$MODEL.zip")
fi
du -sh "models/$MODEL"

echo "== grammar from bank.json"
"$PY" -m voice.grammar "models/$MODEL" models/vosk_grammar.device.json
if cmp -s <(python3 -c "import json,sys; d=json.load(open('models/vosk_grammar.device.json')); print(json.dumps(d['words']))") \
          <(python3 -c "import json,sys; d=json.load(open('grammar/vosk_grammar.json')); print(json.dumps(d['words']))"); then
  echo "grammar on the device = grammar/vosk_grammar.json"
else
  echo "WARNING: the device grammar differs from grammar/vosk_grammar.json"
fi

echo "== headset mic (bluez-alsa HFP/HSP)"
# The headset's mic is its HFP/HSP profile. bluez-alsa on Raspberry Pi OS starts with
# A2DP only; this drop-in adds the headset profiles. Remove the file to undo.
DROPIN=/etc/systemd/system/bluealsa.service.d/pocket-hfp.conf
if command -v bluealsa >/dev/null && [ ! -f "$DROPIN" ]; then
  sudo mkdir -p "$(dirname "$DROPIN")"
  printf "[Service]\nExecStart=\nExecStart=/usr/bin/bluealsa -S -p a2dp-source -p a2dp-sink -p hfp-ag -p hsp-ag\n" | sudo tee "$DROPIN" >/dev/null
  sudo systemctl daemon-reload && sudo systemctl restart bluealsa
  echo "bluealsa restarted with hfp-ag and hsp-ag: reconnect the headset"
fi
command -v bluealsa-cli >/dev/null && bluealsa-cli list-pcms || true

echo "== audio"
for t in parec pw-record arecord pactl wpctl bluetoothctl; do printf '%-12s %s\n' "$t" "$(command -v $t || echo -)"; done
command -v pactl >/dev/null && { pactl info | grep -E "Server Name|Default Source"; pactl list short sources; pactl list cards | grep -E "Name: bluez|Active Profile"; } || true
command -v bluetoothctl >/dev/null && bluetoothctl devices Connected || true

echo "== input devices (push-to-talk)"
grep -E '^N: Name=|^H: Handlers=' /proc/bus/input/devices | paste - - || true
