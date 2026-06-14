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

## Loop iteration 3 — DONE
- Per-side USB product strings: `config/bootloader_touch_{left,right}.conf`
  (self-contained; CONFIG_USB_DEVICE_PRODUCT "Cradio L"/"R"), wired per cradio
  entry in build.yaml. Removed the shared bootloader_touch.conf. -> `list` and
  product-fallback calibration now distinguish halves with both plugged in.
- `kbd-flash flash --dry-run`: resolves + prints the plan, touches nothing.
- DTR-drop gating DECISION: NOT implementing. The udev ModemManager-ignore rule
  already removes the only realistic accidental trigger; adding DTR-close gating
  would add firmware complexity and break the simple `stty 1200` convention for
  marginal benefit. Revisit only if a bench test shows spurious triggers.
- 38 host tests + 1500-trial fuzz + native_sim fw test green.

## Loop iteration 4 — DONE
- CI for per-side product (run 27511813516): GREEN.
- verify-after-flash: added an INDEPENDENT product-string cross-check after
  re-enumeration (resolve_side is deterministic-from-cid under calibration, so
  it can't catch a wrong-image flash; the product check can). New sim fault
  `corrupt_flash_side` + regression test + added to fuzz. 39 tests green.

## Loop iteration 5 — DONE
- README.md (what it does, firmware+host flow, setup/udev/calibrate/flash, dev).
- pyproject.toml: `kbd-flash` console_script (verified `pip install -e .` ->
  `kbd-flash --sim list` works). egg-info gitignored.
- 39 tests green. SOFTWARE COMPLETE — switching loop to long idle intervals;
  only hardware-gated bench work remains (BENCH.md).

## Status: software side is feature-complete pending bench
Firmware validated (native_sim+usbip + CI ARM incl GPREGRET path), orchestrator
robust (39 tests, 1500-trial fuzz over 6 fault dimensions), CLI (list/calibrate/
flash/--dry-run), udev mitigation, per-side identity, verify-after-flash, docs
(BENCH.md, PROGRESS.md). Remaining work is HARDWARE-ONLY (needs Cedar + bench).

## Next steps (priority order)
1. [ ] Everything in "Hardware-only" below — needs Cedar + bench (see BENCH.md).
2. [ ] Loop should avoid over-engineering (YAGNI): only add coverage/docs that
       reflect a real, plausible failure mode — not busywork. Candidate small
       wins if ideas arise: a tool README, packaging kbd-flash as an installable
       entrypoint, deeper property-based fuzzing of timing races.

## Hardware-only (cannot test here, verify on bench)
- The actual GPREGRET→UF2 handoff (native_sim has no retention reg).
- The bootloader's mass-storage mount + chip-id serial correlation on Linux.
- Real nice!nano CDC enumeration timing.
