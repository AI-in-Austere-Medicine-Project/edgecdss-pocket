#!/usr/bin/env bash
# Memory guard on the Pi Zero 2 W (415 MB). Safe to run again.
#   bash device/memory.sh
#
# 1. A 512 MB swap file, so a spike slows the board instead of the kernel killing
#    whatever it picks. Swappiness 10: the model's pages stay in RAM unless memory is short.
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
if ! swapon --show=NAME --noheadings | grep -qx "$SWAPFILE"; then
  if [ ! -f "$SWAPFILE" ]; then
    sudo fallocate -l ${SWAP_MB}M "$SWAPFILE" || sudo dd if=/dev/zero of="$SWAPFILE" bs=1M count=$SWAP_MB status=none
    sudo chmod 600 "$SWAPFILE"
    sudo mkswap -q "$SWAPFILE"
  fi
  sudo swapon "$SWAPFILE"
fi
grep -q "^$SWAPFILE " /etc/fstab || echo "$SWAPFILE none swap sw 0 0" | sudo tee -a /etc/fstab >/dev/null
echo "vm.swappiness=10" | sudo tee /etc/sysctl.d/90-pocket-swap.conf >/dev/null
sudo sysctl -q -p /etc/sysctl.d/90-pocket-swap.conf
swapon --show
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
