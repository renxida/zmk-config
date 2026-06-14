#!/usr/bin/env bash
# macOS helper to validate / use the usb-bootloader-touch firmware.
# The Python kbd-flash orchestrator is Linux-only (udev/lsblk); on macOS this
# script does the host-OS-agnostic core: 1200-baud touch -> bootloader -> flash.
#
# Usage:
#   ./mac_touch.sh                      # touch the first cu.usbmodem*, prove bootloader entry
#   ./mac_touch.sh <port>               # touch a specific port
#   ./mac_touch.sh <port> <file.uf2>    # touch, then flash the uf2 (reset-free)
#   ./mac_touch.sh auto <file.uf2>      # auto-pick port, then flash
set -uo pipefail

PORT="${1:-auto}"
UF2="${2:-}"

if [ "$PORT" = auto ] || [ -z "$PORT" ]; then
  PORT=$(ls /dev/cu.usbmodem* 2>/dev/null | head -1) || true
  [ -n "$PORT" ] || { echo "no /dev/cu.usbmodem* found — is a half plugged in over USB?"; exit 1; }
fi
echo "port: $PORT"

# Record the running serial (chip id) before we touch, for the byte-order note.
echo "running USB serial (via ioreg):"
ioreg -p IOUSB -l 2>/dev/null | grep -A40 -i "$(basename "$PORT" | sed 's/cu\.//')" 2>/dev/null \
  | grep -i '"USB Serial Number"' | head -1 || echo "  (couldn't read; try: system_profiler SPUSBDataType)"

echo "== touching $PORT (prime 9600 -> 1200, the trigger) =="
# The watcher fires on a baud *change* to 1200. macOS sets the rate on first
# open, so a bare `stty 1200` is a no-op change. Prime to 9600 then 1200 within
# one open (termios), which sends SetLineCoding(9600) then (1200).
python3 - "$PORT" <<'PY' || { echo "touch failed (port busy?)"; exit 1; }
import sys, os, termios, time
fd = os.open(sys.argv[1], os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
try:
    a = termios.tcgetattr(fd)
    for sp in (termios.B9600, termios.B1200):
        a[4] = sp; a[5] = sp
        termios.tcsetattr(fd, termios.TCSANOW, a)
        time.sleep(0.3)
finally:
    os.close(fd)
PY

echo "== waiting up to 15s for NICENANO to mount (NO physical reset) =="
VOL=""
for _ in $(seq 1 30); do
  VOL=$(ls -d /Volumes/NICENANO* 2>/dev/null | head -1) || true
  [ -n "$VOL" ] && break
  sleep 0.5
done
if [ -z "$VOL" ]; then
  echo "FAIL: NICENANO did not mount — the 1200 touch did not enter the bootloader."
  echo "      (Confirm this half is running the touch-enabled firmware.)"
  exit 1
fi
echo "PASS: $VOL mounted with no physical reset — bootloader entry works."

# Bootloader serial (chip id as the Adafruit bootloader formats it) for the note.
echo "bootloader USB serial (via ioreg):"
ioreg -p IOUSB -l 2>/dev/null | grep -i '"USB Serial Number"' | tail -1 || true

if [ -n "$UF2" ]; then
  [ -f "$UF2" ] || { echo "uf2 not found: $UF2"; exit 1; }
  echo "== flashing $(basename "$UF2") -> $VOL =="
  cp "$UF2" "$VOL/" 2>/dev/null || true   # bootloader yanks the volume mid-copy; normal
  sync
  echo "copied; the half will reboot into the new firmware."
fi
