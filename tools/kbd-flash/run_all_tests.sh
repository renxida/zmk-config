#!/usr/bin/env bash
# One feedback-loop command: host orchestrator unit/fuzz tests + the firmware
# native_sim+usbip end-to-end touch test. Returns non-zero if anything fails.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
rc=0

echo "=================================================="
echo "  host orchestrator tests (unit + fuzz)"
echo "=================================================="
( cd "$HERE" && python3 -m unittest 2>&1 | tail -4 ) || rc=1

echo
echo "=================================================="
echo "  firmware native_sim + usbip touch test"
echo "=================================================="
if [ -d "$HOME/zephyrproject/zephyr" ]; then
  "$REPO/zmk_modules/usb-bootloader-touch/tests/native_sim/run_test.sh" 2>&1 | tail -6 || rc=1
else
  echo "SKIP: no zephyr workspace (~/zephyrproject); firmware test not run"
fi

echo
if [ "$rc" = 0 ]; then echo "ALL GREEN"; else echo "FAILURES (rc=$rc)"; fi
exit $rc
