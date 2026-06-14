# kbd-flash / usb-bootloader-touch — progress & next steps

Self-updating status for the autonomous improvement loop. Running on
**dev-machine-3** (Ubuntu 24.04 DO droplet). Branch: `feat/usb-bootloader-touch`.

## Goal
Plug both split halves into USB, run one command, walk away → both flashed with
the correct firmware and BT cleared, no physical reset. Two pieces:
1. **Firmware** `zmk_modules/usb-bootloader-touch/` — host opens CDC at 1200 baud
   → reboot into UF2 bootloader (the Arduino touch, reproduced in ZMK since the
   nRF52840 bootloader doesn't do baud detection).
2. **Host** `tools/kbd-flash/` — identify halves by chip-id, serialized 2-stage
   flash (settings_reset → cradio_<side>), routed by calibration map.

## Done & verified
- [x] Firmware module: event-driven via `cdc_acm_dte_rate_callback_set`,
      defers reboot to workqueue. Compiles clean on native_sim.
- [x] **End-to-end firmware test passes** (`tests/native_sim/run_test.sh`):
      native_sim + usbip, host 1200-baud open → "1200-baud touch detected →
      entering UF2 bootloader". 9600 negative control ignored.
- [x] Host orchestrator + device simulator: 30 tests incl 1500-trial fuzz.
- [x] Linux RealPlatform + parser unit tests.
- [x] **CI ARM compile-check GREEN** — module builds into real cradio_left/right
      via zmk-usb-logging snippet + ZMK_EXTRA_MODULES (exercises the real
      RETENTION_BOOT_MODE/GPREGRET reboot path). settings_reset untouched.
- [x] CLI: `list` / `calibrate` / `flash` (+ `--sim`); calibration builder.
- [x] Hardening: debounced discovery (flap absorption), chip-id collision guard,
      single-half support.
- [x] **Bug found+fixed by fuzz**: bootloader detection by chip-id matching
      could cross-contaminate (a prior half stuck in bootloader got the next
      half's fw). Now: identify bootloader as the volume NOT present before we
      touched THIS half (`foreign` exclusion) — also robust to NICENANO-1
      double-mount. Regression test added.
- [x] Step 3 config added (HWINFO + USB_DEVICE_SN -> running serial = chip id);
      pending CI re-verify.

## Key design decision
Bootloader correlation does NOT rely on running-serial == bootloader-serial
(nRF hwinfo vs Adafruit bootloader may format the device id with different byte
order — UNVERIFIED on hw). Serialized flashing + "new/non-foreign volume after
touch" sidesteps it. Running serial (= chip id via hwinfo) is only used for
calibration (side mapping) and post-flash re-identification, where stability +
uniqueness is all that's needed.

## Environment (already set up)
- Zephyr 3.7.0 workspace at `~/zephyrproject`, venv `~/.venv-zephyr`.
- Build: `ZEPHYR_BASE=~/zephyrproject/zephyr ZEPHYR_TOOLCHAIN_VARIANT=host ~/.venv-zephyr/bin/west build -p always -b native_sim -d /tmp/bltouch-build <app>`
- usbip: `vhci-hcd` loaded; `linux-modules-extra-$(uname -r)` installed. DO NOT
  reboot (pending kernel -124 would break the -71 vhci module).
- Host tests: `cd tools/kbd-flash && python3 -m unittest -q`
- FW test: `zmk_modules/usb-bootloader-touch/tests/native_sim/run_test.sh`

## Loop iteration 1 — DONE
Steps 1 (CI ARM build, green), 2 (CLI + calibrate incl one-at-a-time --side),
3 (HWINFO serial, green), 4 (hardening + fuzz-found cross-contamination bug),
6 (BENCH.md). Unified runner: `tools/kbd-flash/run_all_tests.sh` (host + fw,
ALL GREEN). 32 host tests + 1500-trial fuzz + native_sim+usbip fw test.

## Loop iteration 2 — DONE
- Accidental-1200-trigger: decided (keep 1200, tool-compatible) + mitigated the
  real threat (ModemManager) with `99-zmk-kbd-flash.rules` (ID_MM_DEVICE_IGNORE
  + user access + stable symlink). Documented in BENCH.md §0b.
- real_platform: match running halves by ZMK VID (1d50) primarily; bootloader
  VID 239a. Edge tests: VID-only match, missing serial, NICENANO-1 double mount,
  empty lsblk.
- Fuzzer: added no_cdc_when_running dimension (undiscovered half) + tolerate the
  no-devices hard error. 36 tests, 1500-trial fuzz, all green.

## Next steps (priority order)
1. [ ] (optional) per-side USB product strings ("Cradio L"/"R") so `list` and
       product-fallback calibration distinguish halves without one-at-a-time.
       Needs per-side EXTRA_CONF in build.yaml (USB_DEVICE_PRODUCT differs).
2. [ ] real_platform: verify-after-flash (confirm the half actually booted the
       new fw, not a silent copy_uf2 OSError-swallow); add a --dry-run.
3. [ ] Consider firmware: require DTR-drop (port close) at 1200 to better match
       the Arduino touch and further reduce spurious triggers (evaluate vs the
       udev mitigation already in place — may be unnecessary).
4. [ ] Everything in "Hardware-only" below — needs Cedar + bench (see BENCH.md).

## Hardware-only (cannot test here, verify on bench)
- The actual GPREGRET→UF2 handoff (native_sim has no retention reg).
- The bootloader's mass-storage mount + chip-id serial correlation on Linux.
- Real nice!nano CDC enumeration timing.
