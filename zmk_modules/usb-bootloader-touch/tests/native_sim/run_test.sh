#!/usr/bin/env bash
# End-to-end test of the usb-bootloader-touch firmware on native_sim:
# build -> run (USBIP server) -> attach via vhci-hcd -> open CDC at 1200 baud
# -> assert the watcher detected the touch.
#
# Needs: zephyr workspace at ~/zephyrproject, vhci-hcd loaded, passwordless
# sudo for usbip attach/detach. Run from anywhere.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
BUILD=/tmp/bltouch-build
RUNLOG=/tmp/bltouch-run.log
export ZEPHYR_BASE=${ZEPHYR_BASE:-$HOME/zephyrproject/zephyr}
export ZEPHYR_TOOLCHAIN_VARIANT=host
WEST="$HOME/.venv-zephyr/bin/west"

SIMPID=""
cleanup() {
  [ -n "$SIMPID" ] && kill "$SIMPID" 2>/dev/null
  sudo usbip detach -p 00 2>/dev/null
}
trap cleanup EXIT

echo "== build =="
"$WEST" build -p always -b native_sim -d "$BUILD" "$HERE" 2>&1 | tail -3 || { echo "BUILD FAILED"; exit 1; }

echo "== run (USBIP server) =="
"$BUILD/zephyr/zephyr.exe" > "$RUNLOG" 2>&1 &
SIMPID=$!
sleep 3
kill -0 "$SIMPID" 2>/dev/null || { echo "sim died"; cat "$RUNLOG"; exit 1; }

echo "== attach via usbip =="
sudo modprobe vhci-hcd 2>/dev/null
BUSID=$(usbip list -r 127.0.0.1 2>/dev/null | grep -oE '^ *[0-9]+-[0-9]+:' | head -1 | tr -d ' :')
[ -n "$BUSID" ] || { echo "no exported device"; exit 1; }
sudo usbip attach -r 127.0.0.1 -b "$BUSID" || { echo "attach failed"; exit 1; }

echo "== wait for /dev/ttyACM* =="
TTY=""
for _ in $(seq 1 20); do
  TTY=$(ls /dev/ttyACM* 2>/dev/null | head -1) && [ -n "$TTY" ] && break
  sleep 0.5
done
[ -n "$TTY" ] || { echo "no ttyACM appeared"; exit 1; }
echo "   got $TTY"
sudo chmod 666 "$TTY"   # usbip-attached node is root-owned; allow user open

echo "== wait for CDC to finish configuring (usbip enum is slow) =="
for _ in $(seq 1 40); do grep -q "Device configured" "$RUNLOG" && break; sleep 0.5; done
grep -q "Device configured" "$RUNLOG" || { echo "CDC never configured"; tail "$RUNLOG"; exit 1; }
sleep 0.5

echo "== negative control: open at 9600 (must NOT trigger) =="
exec 3<>"$TTY"; stty -F "$TTY" 9600 2>/dev/null; sleep 1; exec 3>&-
if grep -q "touch detected" "$RUNLOG"; then echo "FAIL: triggered at 9600"; exit 1; fi
echo "   ok, no trigger at 9600"

echo "== the touch: hold CDC open at 1200 baud =="
exec 3<>"$TTY"; stty -F "$TTY" 1200 2>/dev/null; sleep 0.3
TRIG=0
for _ in $(seq 1 16); do grep -q "1200-baud touch detected" "$RUNLOG" && { TRIG=1; break; }; sleep 0.25; done
exec 3>&-

echo "== assert =="
if [ "$TRIG" != 1 ]; then
  echo "FAIL: no trigger in log"; tail -10 "$RUNLOG"; exit 1
fi
echo "PASS: watcher detected 1200-baud touch and scheduled bootloader"
grep "touch detected\|entering UF2\|would enter" "$RUNLOG" | tail -3

# RECOVERABILITY contract: an early POST_KERNEL erase (mirrors zmk_settings_erase)
# ran at boot, yet CDC enumerated and the watcher still fired. This is the
# property that makes settings_reset_touch safe to flash.
if grep -q "mock: settings erased" "$RUNLOG"; then
  echo "PASS: recoverability — early POST_KERNEL erase ran, CDC+touch still live"
else
  echo "FAIL: recoverability — early erase init did not run (compiled out?)"; exit 1
fi
exit 0
