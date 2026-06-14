# Bench test plan — usb-bootloader-touch (do WITH Cedar + real keyboards)

Everything below the line "VERIFY ON HARDWARE" can't be emulated. Order matters.

## 0. Get the touch-enabled firmware
CI artifact from branch `feat/usb-bootloader-touch` (build "Build ZMK firmware
(nix)") contains `cradio_left`/`cradio_right` built WITH the feature, plus
`settings_reset`. Download to `~/zmk-config/firmware/`.

    gh run download <run-id> -D ~/zmk-config/firmware

## 0b. Host setup (do once) — accidental-trigger mitigation
The watcher reboots to bootloader on ANY 1200-baud open of the CDC console.
The real risk is **ModemManager** probing the new ttyACM (it cycles baud rates,
could hit 1200, and drop your keyboard into the bootloader mid-use). Decision:
keep the 1200 trigger (standard, tool-compatible) and stop ModemManager from
touching the device via udev:

    sudo cp tools/kbd-flash/99-zmk-kbd-flash.rules /etc/udev/rules.d/
    sudo udevadm control --reload && sudo udevadm trigger

This also grants user access (no sudo chmod) and a stable `/dev/zmk-<serial>`
symlink. VERIFY VID/PID with `lsusb` first (rule assumes ZMK 1d50:615e). With
the rule installed, a deliberate `stty 1200` still triggers (that's the touch);
only background probing is prevented.

## 1. Bootstrap install (ONE manual reset per half — unavoidable)
The halves currently run firmware WITHOUT the touch feature, so the first
install still needs a physical reset.
- Double-tap reset on the LEFT half over USB → flash `cradio_left-*.uf2`
  (this version has the 1200-baud watcher).
- Repeat for the RIGHT half → `cradio_right-*.uf2`.
(Reuse the proven watch-loop copy approach.)

## 2. Confirm running halves expose a CDC serial + chip id
With a half plugged in:

    kbd-flash list      # should show the half with a chip_id (= FICR.DEVICEID)

VERIFY: a `/dev/ttyACM*` appears (zmk-usb-logging CDC), and udev
`ID_SERIAL_SHORT` is a 16-hex chip id. If no ttyACM → CDC/snippet problem.

## 3. Calibrate (one-at-a-time, bulletproof)
    # plug in ONLY the left half:
    kbd-flash calibrate --side left
    # plug in ONLY the right half:
    kbd-flash calibrate --side right
Writes ~/.config/kbd-flash/calibration.json (chip_id -> side).

## 4. THE TEST: USB-triggered bootloader, no physical reset
Plug in ONE half. The watcher fires on a baud *change* to 1200, and the OS may
set the rate on first open — so PRIME to another rate first:

    # Linux: stty -F /dev/ttyACM0 9600 ; stty -F /dev/ttyACM0 1200
    # macOS: use mac_touch.sh (opens once, sets 9600 then 1200 via termios)
    tools/kbd-flash/mac_touch.sh        # or kbd-flash's touch_1200 on Linux

A bare `stty 1200` is a no-op change and will NOT trigger — confirmed on macOS.

VERIFY ON HARDWARE (the parts native_sim could not):
- [ ] After the primed 9600->1200 touch, the half reboots and `NICENANO`
      mass-storage mounts (exercises the real GPREGRET=0x57 -> UF2 handoff).
      NOTE: the first hardware run reached the reboot but landed in normal fw —
      the build had RETENTION_BOOT_MODE off so the magic was never written.
      Fixed: nRF52 now writes 0x57 to GPREGRET[0] directly (run 27514396150+).
- [x] Running serial vs bootloader serial: SETTLED — identical 16-hex, no byte
      reorder (e.g. 8905AEEAAFB95703). The orchestrator does not rely on this.

## 5. Full automated flow
Plug in BOTH halves, then:

    kbd-flash flash            # wipes BT + flashes both, no reset
    kbd-flash flash --no-wipe  # keep BT bonds

VERIFY:
- [ ] Each half: touch -> settings_reset -> cradio_<side> -> re-enumerates.
- [ ] Correct fw per side (left gets cradio_left). Check BLE name / behavior.
- [ ] Halves re-pair to each other and to the host.

## Known risks to watch
- Enumeration timing: real nice!nano CDC may configure slower/faster than the
  ~5s seen in native_sim; the host waits are generous but confirm.
- `copy_uf2` OSError-on-yank is treated as success — confirm the flash actually
  took (the half boots the new fw), not a silent failure.
- Only ONE half enumerates per USB cable; the orchestrator serializes, so plug
  both into the same host and it does them in turn.
