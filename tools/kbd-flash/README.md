# kbd-flash

Flash a ZMK split keyboard over USB with **no physical reset** — plug both
halves in, run one command, walk away. Each half gets the correct firmware
(routed by chip id) and, optionally, its Bluetooth bonds wiped.

**Status:** host-triggered reset-free bootloader entry + reflash is validated on
real nice!nano v2 hardware — 5/5 trials on the left half (immediate and settled
touches). Right half runs identical firmware (expected to work, not yet tested).
The host orchestrator (`kbd-flash`) is Linux-only; on macOS use `mac_touch.sh`.

This pairs a small ZMK firmware feature with a host orchestrator:

- **Firmware** (`../../zmk_modules/usb-bootloader-touch/`): reboots a half into
  the UF2 bootloader when the host opens its CDC port at **1200 baud** — the
  Arduino "1200bps touch", reproduced in ZMK because the nRF52840 Adafruit
  bootloader doesn't do baud-triggered DFU itself. Host-triggered
  bootloader-over-USB does not exist upstream (see ZMK issue #2635).
- **Host** (this dir): identifies halves by their nRF chip id (FICR.DEVICEID,
  exposed as the USB serial), serializes a two-stage flash per half
  (settings_reset → cradio_<side>), and verifies each half re-enumerates with
  the right firmware.

## Why it's safe to route
- Halves are identified by **chip id**, mapped to side once via `calibrate`.
- Flashing is **serialized**: only one half enters the bootloader at a time, so
  the newly-appearing `NICENANO` volume is unambiguous (no chip-id matching
  across running/bootloader modes needed — their serial byte-order may differ).
- After flashing, an **independent product-string cross-check** confirms the
  right image actually booted on the right half.

## Setup (once)
1. Build/flash the touch-enabled firmware. The CI artifact from branch
   `feat/usb-bootloader-touch` has it. First install needs ONE manual reset per
   half (the running firmware must already contain the feature). See `BENCH.md`.
2. Install the udev rule (stops ModemManager from accidentally tripping the
   1200-baud touch, grants user access, adds a stable symlink):

       sudo cp 99-zmk-kbd-flash.rules /etc/udev/rules.d/
       sudo udevadm control --reload && sudo udevadm trigger

3. Calibrate chip id → side (one-at-a-time is bulletproof):

       kbd-flash calibrate --side left     # only the left half plugged in
       kbd-flash calibrate --side right     # only the right half plugged in

   (Or, with per-side product strings flashed, plug both in and run
   `kbd-flash calibrate` to infer from the product strings.)

## Use
    kbd-flash list                 # show running halves + bootloader volumes
    kbd-flash flash --dry-run      # show the plan, touch nothing
    kbd-flash flash                # wipe BT + flash both halves
    kbd-flash flash --no-wipe      # keep BT bonds

`--fw-dir` (default `~/zmk-config/firmware`) holds the `.uf2` files;
newest matching `*left*`, `*right*`, `*settings_reset*` are picked.

## Develop / test
    ./run_all_tests.sh             # host unit+fuzz tests AND the native_sim fw test
    python3 -m unittest            # host tests only (no Zephyr needed)

The simulator (`sim.py`) models a virtual keyboard pair as a clocked state
machine, so the orchestrator is exercised end-to-end — including failure modes
(dead CDC, bricked flash, stuck bootloader, enumeration flap, wrong image) — via
a 1500-trial fuzz, with no hardware. The firmware's 1200-baud detection is
verified for real on `native_sim` + `usbip`
(`../../zmk_modules/usb-bootloader-touch/tests/native_sim/run_test.sh`).

## Files
- `kbd_flash.py` — orchestrator + platform interface + identity/routing
- `real_platform.py` — Linux platform (udev/lsblk/termios); pure parsers tested
- `sim.py` — simulated keyboard pair (the test target)
- `cli.py` — `list` / `calibrate` / `flash`
- `99-zmk-kbd-flash.rules` — udev rule (ModemManager ignore + access + symlink)
- `BENCH.md` — the on-hardware test plan
