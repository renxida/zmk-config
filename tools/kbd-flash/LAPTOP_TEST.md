# Hardware test runbook — for the laptop's Claude (macOS)

You are on Cedar's MacBook with the two real Cradio halves. Goal: validate the
`usb-bootloader-touch` firmware — **reboot a half into the UF2 bootloader by
opening its USB CDC port at 1200 baud, with NO physical reset.** That's the one
thing that could only be confirmed on real hardware.

Context: the firmware was built & validated on a Linux dev box (native_sim +
usbip, and CI ARM build incl. the real GPREGRET reboot path). The Python
`kbd-flash` orchestrator is **Linux-only** (udev/lsblk). On macOS use the
`mac_touch.sh` helper here — it does the host-OS-agnostic core (touch → wait for
NICENANO → optionally copy a .uf2). Full Mac automation of the two-half flow is
a possible follow-up (port the platform to ioreg/diskutil) but is NOT needed to
validate the firmware.

## Prereqs
- `gh` authenticated (account renxida).
- This repo on the laptop: `gh repo clone renxida/zmk-config` (or pull), then
  `cd zmk-config && git checkout feat/usb-bootloader-touch`.
- `chmod +x tools/kbd-flash/mac_touch.sh`

## 1. Get the touch-enabled firmware
    gh run download 27511813516 -R renxida/zmk-config -D ~/kbd-fw
    ls ~/kbd-fw/**/*.uf2     # expect cradio_left / cradio_right / settings_reset
The `cradio_*` images here include the 1200-baud touch feature; the halves do
NOT have it yet (they run the older firmware flashed earlier).

## 2. Identify the halves
    ls /dev/cu.usbmodem*
    system_profiler SPUSBDataType | grep -iA6 "nice\|nordic\|zmk\|cradio"
Note each half's USB serial number (= nRF chip id) and which `cu.usbmodem*` it is.

## 3. Bootstrap-install the touch firmware (ONE manual reset per half — unavoidable)
The current firmware can't be touched into the bootloader (no feature yet), so
the first install needs a physical double-tap reset. For EACH half:
- Double-tap the nice!nano reset button → `NICENANO` mounts at `/Volumes/NICENANO`.
- Copy the matching image (LEFT half → cradio_left, RIGHT half → cradio_right):
      cp ~/kbd-fw/**/cradio_left-*.uf2 /Volumes/NICENANO/    # left half
After both halves: they now run the touch-enabled firmware.

## 4. THE TEST — reset-free bootloader entry (the whole point)
Plug in ONE half. Then:
    tools/kbd-flash/mac_touch.sh                # auto-picks the cu.usbmodem port
Expect: `PASS: /Volumes/NICENANO mounted with no physical reset`.
If it mounts WITHOUT you touching the reset button — the feature works. 🎉
(If FAIL: confirm step 3 actually installed the touch firmware on this half.)

## 5. Reset-free reflash (the actual use case)
    tools/kbd-flash/mac_touch.sh auto ~/kbd-fw/**/cradio_left-*.uf2
Touch → NICENANO mounts → copies the image → half reboots into it. No reset.
For a full BT wipe, flash settings_reset first, then the cradio image:
    tools/kbd-flash/mac_touch.sh auto ~/kbd-fw/**/settings_reset-*.uf2
    # half re-presents the bootloader; then:
    tools/kbd-flash/mac_touch.sh auto ~/kbd-fw/**/cradio_left-*.uf2

## 6. Report back to Cedar / the dev-box Claude
- [ ] Did step 4 mount NICENANO with no physical reset? (core result)
- [ ] How long after the `stty 1200` did it mount? (enumeration timing)
- [ ] The two serial numbers `mac_touch.sh` printed: the **running** USB serial
      vs the **bootloader** USB serial. Are they the same 16-hex string or
      byte-reordered? (Settles the open question in BENCH.md — the orchestrator
      doesn't depend on them matching, but good to know.)
- [ ] Did step 5 leave the half running the new firmware (re-enumerates, types)?
- [ ] Any snags (port busy, didn't trigger, wrong image, re-pairing issues).

## Safety note
macOS has no ModemManager, so the accidental-1200-trigger risk (the reason for
the Linux udev rule) is effectively nil here. Only your deliberate
`stty 1200` / `mac_touch.sh` triggers the bootloader.
