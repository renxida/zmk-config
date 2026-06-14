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

echo "== touching $PORT at 1200 baud (the trigger) =="
stty -f "$PORT" 1200 || { echo "stty failed (port busy? ModemManager-equivalent?)"; exit 1; }

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
