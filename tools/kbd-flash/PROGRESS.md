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

## Next steps (priority order)
1. [ ] Integrate the module into the REAL cradio ZMK build + push branch so CI
       does the ARM compile-check (renxida/zmk-actions). Wire chosen
       `zmk,bootloader-touch-uart` to the zmk-usb-logging CDC; add `snippet:
       zmk-usb-logging` + the module to build. Confirm GPREGRET path compiles
       with RETENTION_BOOT_MODE (the real reboot path, untested on native_sim).
       CI MECHANICS (confirmed from renxida/zmk-actions build-user-config.yml):
       - per build.yaml entry: `snippet: zmk-usb-logging` -> `-S`, and
         `cmake-args:` is appended to the west build line verbatim.
       - pass `cmake-args: -DZMK_EXTRA_MODULES=${GITHUB_WORKSPACE}/zmk_modules/usb-bootloader-touch`
         (GITHUB_WORKSPACE expands in the build step shell).
       - zmk-usb-logging snippet's CDC node is labelled
         `snippet_zmk_usb_logging_uart`; chosen overlay should set
         `zmk,bootloader-touch-uart = &snippet_zmk_usb_logging_uart`.
       OPEN QUESTION to resolve WITH CI: how config/*.conf + *.overlay apply
       per shield in THIS repo (config has cradio.conf + cradio.keymap but
       shields are cradio_left/right — verify the include mechanism before
       adding CONFIG_USB_BOOTLOADER_TOUCH=y so it lands on the right builds).
       SAFE APPROACH: add separate touch artifacts first (don't break the 3
       working builds), confirm green, then fold into main cradio_left/right.
       Use the ci-wait skill / `gh run watch` to monitor; iterate on errors.
2. [ ] `kbd-flash-all` CLI entrypoint + `calibrate` subcommand (learn chip→side).
3. [ ] Set ZMK running USB serial = FICR.DEVICEID + product "Cradio L/R" per
       side (so host identifies running halves, not just bootloader).
4. [ ] Harden harness: flapping discovery, "NICENANO 1" double-mount naming,
       partial/anti-flap debounce, chip-id collision, calibration vs product
       disagreement. Add to sim fuzz dimensions.
5. [ ] native_sim: model the full flash *sequence* (settings_reset re-present)
       if feasible; otherwise document hardware-only gaps.
6. [ ] Bench checklist for testing with real keyboards (the part only Cedar can
       do): first manual reset to install touch fw, then USB-triggered reflash.

## Hardware-only (cannot test here, verify on bench)
- The actual GPREGRET→UF2 handoff (native_sim has no retention reg).
- The bootloader's mass-storage mount + chip-id serial correlation on Linux.
- Real nice!nano CDC enumeration timing.
