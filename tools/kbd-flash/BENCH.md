# Bench test plan — usb-bootloader-touch (do WITH Cedar + real keyboards)

Everything below the line "VERIFY ON HARDWARE" can't be emulated. Order matters.

## 0. Get the touch-enabled firmware
CI artifact from branch `feat/usb-bootloader-touch` (build "Build ZMK firmware
(nix)") contains `cradio_left`/`cradio_right` built WITH the feature, plus
`settings_reset`. Download to `~/zmk-config/firmware/`.

    gh run download <run-id> -D ~/zmk-config/firmware

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
Plug in ONE half. Manually trigger just the touch first to de-risk:

    stty -F /dev/ttyACM0 1200      # should drop the half into the UF2 bootloader

VERIFY ON HARDWARE (the parts native_sim could not):
- [ ] After `stty 1200`, the half reboots and `NICENANO` mass-storage mounts
      (this exercises the real GPREGRET=0x57 -> UF2 handoff).
- [ ] `lsblk -o NAME,LABEL,MOUNTPOINT,SERIAL` shows the NICENANO volume; note
      its serial (Adafruit bootloader's chip id) vs the running ID_SERIAL_SHORT
      — RECORD whether they're byte-identical or reordered (informs whether
      cross-mode chip-id matching could ever be re-enabled; current code does
      NOT rely on it).

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
