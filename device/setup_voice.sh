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

echo "== grammar"
# The grammar is generated on the bench (python3 -m voice.grammar MODEL); here only check
# that it was made for this model and this bank. Loading the model twice on a Zero 2 W
# (415 MB) is avoided.
"$PY" - "models/$MODEL" <<'PYEOF'
import json, pathlib, sys
from engine.bank import load_bank
from voice.grammar import model_id
g = json.loads(pathlib.Path("grammar/vosk_grammar.json").read_text())
m = model_id(sys.argv[1])
assert g["model_am_sha256"] == m["model_am_sha256"], "grammar/vosk_grammar.json is for another model"
assert g["bank_hash"] == load_bank("bank").hash, "grammar/vosk_grammar.json is for another bank"
print(f"grammar ok: {len(g['words'])} entries, model {m['model']}, bank {g['bank_hash'][:8]}")
PYEOF

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
