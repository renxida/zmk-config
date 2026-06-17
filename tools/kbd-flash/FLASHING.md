# Flashing the Cradio — runbook

Canonical "how to flash this keyboard" guide. The keyboard is a **Cradio (Sweep)**:
34-key Colemak-DH BLE split, two **nice!nano v2** (nRF52840) halves running ZMK.
Left = split **central** (`cradio_left`), right = **peripheral** (`cradio_right`).
Firmware ships the **usb-bootloader-touch** feature (PR #5/#6), so a half can be
put into its bootloader over USB with **no physical reset**.

> Cedar has **two pairs**. Identify a pair by **switch color**; identify a half by
> its **chip serial** (= the bootloader's USB serial). Known so far — white pair:
> left `8905AEEAAFB95703` (central), right `32AA4109F019FEAF` (peripheral). The blue
> pair has different serials: read them fresh.

## 0. Get firmware
Built by GitHub Actions on `renxida/zmk-config` (main). Download a run's artifacts:
```
gh run download <run_id> -R renxida/zmk-config -D ~/kbd-fw
# -> cradio_left-…uf2, cradio_right-…uf2, settings_reset(_touch).uf2  (+ .hex/.zip for serial DFU)
```

## 1. Identify halves (which port is which chip)
```
python3 tools/kbd-flash/macos/portmap.py     # prints "<chip_serial> <cu_port>"
ioreg -p IOUSB -l -w0 | grep -iE '"USB Product Name"|"USB Serial Number"'
```
USB product strings tell you the mode: `Cradio L`/`Cradio R` = running cradio fw;
`Cradio Reset` = settings_reset_touch; `nice_nano`/`nice_nano v2` (vendor "Nice
Keyboards") = **in the bootloader**.

## 2. Enter the bootloader (per half)
- **Reset-free (preferred):** `python3 tools/kbd-flash/macos/mac_touch.py <chip_serial>`
  (opens the CDC port, baud 9600→1200; the *change* fires the watcher → reboot to
  bootloader). Plain `stty 1200` does **not** work on macOS.
- **First install / no touch fw yet:** physically **double-tap** the nice!nano reset.

## 3. Flash — pick ONE path
**A. MSC drag-drop (simplest, when NICENANO mounts):**
```
cp ~/kbd-fw/cradio_left-…uf2 /Volumes/NICENANO/    # verify the bootloader serial == the chip first!
```
**B. Serial DFU (robust, macOS-mount-independent — use when NICENANO won't mount):**
```
python3 -m venv ~/.venv-nrfdfu && ~/.venv-nrfdfu/bin/pip install adafruit-nrfutil pyserial   # once
python3 tools/kbd-flash/macos/serial_dfu.py <chip_serial> ~/kbd-fw/cradio_left-…uf2
```
(handles uf2→hex→DFU-zip and `--touch` automatically; direct DFU when already in
the bootloader. See [macos/](macos/) and `reference-nicenano-serial-dfu` memory.)

## 4. Fix split pairing (`Security failed err 2` / one half "doesn't work")
`err 2` = `BT_SECURITY_ERR_PIN_OR_KEY_MISSING` = **mismatched BLE bonds** (common
after reflashing one half). Fix = wipe bonds on **both** halves, then reflash:
1. Flash **`settings_reset_touch`** to BOTH halves (erases NVS/bonds on boot; it's
   touch-capable so still recoverable). 2. Flash `cradio_left`/`cradio_right` back.
3. Power-cycle both → they re-bond fresh. Verify on the central's CDC log:
   `[SUBSCRIBED]` + `security_changed … level 2` (success), and no more `err 2`.

## Gotchas (learned the hard way)
- **Don't thrash the MSC mount.** Hundreds of rapid mount/touch/DFU cycles **wedge
  the macOS USB stack** — NICENANO stops mounting and serial DFU returns "No data
  received". Fix = **physically replug both halves** (or reboot). Prefer serial DFU
  to minimize mount cycles.
- **err-2 loop blocks the touch.** A central stuck retrying a bad bond floods BLE
  and starves USB, so the 1200-baud touch won't fire. Quiet the partner first
  (put it in bootloader / on settings_reset).
- **Always serial-guard the target chip** before writing (left vs right), or you'll
  flash the wrong side and break pairing.
- The host BLE bond (keyboard↔computer) is **separate** from the split bond; if the
  host connection is flaky after a fix, forget+re-add the keyboard on the host.

## 5. Diagnose BT / battery / split issues — `kbd_doctor.py`
One tool for autonomous debugging (macOS). BLE features need the bleak venv:
```bash
python3 -m venv ~/.venv-ble && ~/.venv-ble/bin/pip install bleak   # one-time
```
```bash
cd tools/kbd-flash/macos
~/.venv-ble/bin/python3 kbd_doctor.py health [pair]   # full report (enum+scan+split+battery)
python3            kbd_doctor.py enum                 # devices + app/BOOTLOADER state (no bleak)
~/.venv-ble/bin/python3 kbd_doctor.py scan [secs]     # BLE names by RSSI, flags keyboards
python3            kbd_doctor.py splitlog <pair|serial> [secs]  # central CDC -> split verdict
~/.venv-ble/bin/python3 kbd_doctor.py battery [name]  # read BLE Battery Service
python3            kbd_doctor.py flash <pair-side> <uf2>  # touch->bootloader->flash->verify (one-shot)
```
- **`flash`** is the robust one-shot: touches the half to the bootloader, **waits for
  the flash channel to enumerate** (fixes the serial-DFU auto-touch race), copies via
  MSC if NICENANO mounts else falls back to serial DFU, then waits for the app. e.g.
  `kbd_doctor.py flash vega-left ~/kbd-fw-pairs/firmware-…/vega_left.uf2`.
- **`splitlog`** verdict distinguishes the real fault (**err 2** = bond mismatch between
  halves) from benign host churn (**err 9** / reason 0x13 = an unbonded BLE client, e.g.
  a battery read, connecting then dropping — NOT a split problem). `[SUBSCRIBED]` only
  appears near boot; capture right after a replug/reflash.
- **`battery`** CONNECTS over BLE (reads at security level 1, no pairing dialog) — only
  the **central/left** level is exposed; the right half needs split-battery firmware.
  The % is a voltage estimate and **reads high while on USB**. Connecting briefly churns
  the central (ZMK drops the unbonded client) — harmless on a spare, avoid mid-use.
- All USB/volume enumeration is in `kbd_lib.py` (pure stdlib, zsh-glob-safe). Known chip
  serials for both pairs live in `kbd_lib.KNOWN`.
