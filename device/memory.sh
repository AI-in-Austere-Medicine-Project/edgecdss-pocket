#!/usr/bin/env bash
# Memory guard on the Pi Zero 2 W (415 MB). Safe to run again.
#   bash device/memory.sh
#
# 1. A 512 MB swap file on the SD card, so a spike slows the board instead of the kernel
#    killing whatever it picks. Raspberry Pi OS already swaps to zram (compressed, in RAM,
#    priority 100); the file sits under it (priority 10) and is used once zram is full.
#    Swappiness is left at the default, which suits zram in front.
# 2. pocket.slice (systemd, user): everything the pocket runs goes in it, with a hard
#    ceiling (MemoryMax) and a small swap allowance (MemorySwapMax). A runaway process
#    is killed by its own cgroup at the ceiling, before the OS runs short.
#    Run under it:  systemd-run --user --scope --slice=pocket.slice -- <command>
#    A later pocket.service sets Slice=pocket.slice.
set -euo pipefail

SWAPFILE=/swapfile
SWAP_MB=512
MEMORY_HIGH=${POCKET_MEMORY_HIGH:-260M}   # reclaim/throttle starts here
MEMORY_MAX=${POCKET_MEMORY_MAX:-300M}     # killed here
MEMORY_SWAP_MAX=${POCKET_MEMORY_SWAP_MAX:-96M}

echo "== swap"
if ! awk 'NR>1{print $1}' /proc/swaps | grep -qx "$SWAPFILE"; then
  if [ ! -f "$SWAPFILE" ]; then
    sudo fallocate -l ${SWAP_MB}M "$SWAPFILE" || sudo dd if=/dev/zero of="$SWAPFILE" bs=1M count=$SWAP_MB status=none
    sudo chmod 600 "$SWAPFILE"
    sudo mkswap -q "$SWAPFILE"
  fi
  sudo swapon -p 10 "$SWAPFILE"
fi
grep -q "^$SWAPFILE " /etc/fstab || echo "$SWAPFILE none swap sw,pri=10 0 0" | sudo tee -a /etc/fstab >/dev/null
cat /proc/swaps
echo "swappiness $(cat /proc/sys/vm/swappiness)"

echo "== pocket.slice"
mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/pocket.slice" <<EOF
[Unit]
Description=EdgeCDSS pocket: memory ceiling

[Slice]
MemoryAccounting=yes
MemoryHigh=$MEMORY_HIGH
MemoryMax=$MEMORY_MAX
MemorySwapMax=$MEMORY_SWAP_MAX
EOF
sudo loginctl enable-linger "$USER"
systemctl --user daemon-reload
grep -q memory "/sys/fs/cgroup/user.slice/user-$(id -u).slice/user@$(id -u).service/cgroup.controllers" \
  && echo "memory controller delegated to the user manager" \
  || echo "WARNING: memory controller not delegated; the limit would not hold"
systemctl --user show pocket.slice -p MemoryHigh -p MemoryMax -p MemorySwapMax
