# Reference: ZMK bootloader entry, USB CDC, split BT bonds (source-cited)

Background for the usb-bootloader-touch + kbd-flash project. nice!nano v2
(nRF52840), ZMK on Zephyr 4.1, Adafruit nRF52 UF2 bootloader. Line numbers are
from each repo's `main` at research time and may drift slightly.

## 1. `settings_reset` — what it actually does
`CONFIG_ZMK_SETTINGS_RESET_ON_START=y` registers `zmk_settings_erase` as a
`SYS_INIT(POST_KERNEL, prio 60)`. It opens the settings flash partition, erases
it, closes it, and **returns** — it does NOT reboot/halt/loop; the system keeps
booting normally afterward.
- `app/src/settings/reset_settings_on_start.c` (the SYS_INIT)
- `app/src/settings/reset_settings_nvs.c` (`zmk_settings_erase`: flash_area_open
  → flash_area_erase → flash_area_close → return)
- The `settings_reset` shield (`app/boards/shields/settings_reset/`) also sets
  `CONFIG_ZMK_BLE=n` (comment: "so splits don't try to re-pair until normal
  firmware is flashed") + `CONFIG_ZMK_DISPLAY=n` + a mock kscan.

**Consequence:** a settings_reset build is just a minimal ZMK image that wipes
NVS once early, then idles. Adding USB CDC + the touch watcher makes it sit
there touch-recoverable, with no BLE to hang — the basis of
`settings_reset_touch`.

## 2. nRF52 UF2 bootloader entry (GPREGRET / boot-mode)
The Adafruit bootloader enters UF2 DFU when it reads magic `0x57`
(`DFU_MAGIC_UF2_RESET`) from `NRF_POWER->GPREGRET[0]` at boot.
- ZMK `&bootloader` behavior: `app/src/behaviors/behavior_reset.c` →
  `bootmode_set(BOOT_MODE_TYPE_BOOTLOADER)` then `sys_reboot(SYS_REBOOT_WARM)`
  (when `CONFIG_RETENTION_BOOT_MODE`).
- The magic mapper that ultimately writes `0x57` to GPREGRET[0]:
  `app/src/boot/bootmode_to_magic_mapper.c`, value from
  `CONFIG_ZMK_BOOTMODE_BOOTLOADER_MAGIC_VALUE` (0x57 for
  `ADAFRUIT_NRF52`, `app/src/boot/Kconfig.defaults`), backed by the `gpregret1`
  retention node (`app/dts/common/nordic/nrf52840_uf2_boot_mode.dtsi`).
- HAL: `nrf_power_gpregret_set(NRF_POWER, 0, 0x57)` /
  `nrf_power_gpregret_get(NRF_POWER, 0)` (nrfx `hal/nrf_power.h`). GPREGRET
  survives a warm/soft reset (NVIC SystemReset), but NOT power-on/pin/brownout.

**The clobber bug we hit:** with `CONFIG_NRF_STORE_REBOOT_TYPE_GPREGRET=y`,
`sys_reboot(kind)` writes `kind` into GPREGRET[0] right before resetting. So
writing `0x57` then calling `sys_reboot(SYS_REBOOT_WARM)` (=0) **clobbers** the
magic to 0 → bootloader sees nothing → normal fw. Fix: `sys_reboot(0x57)` (magic
as the reboot type). Validated 5/5 on both halves. See `usb_bootloader_touch.c`.

## 3. USB CDC + the 1200-baud touch
- `CONFIG_ZMK_USB_LOGGING=y` (via the `zmk-usb-logging` snippet) brings up a USB
  CDC ACM port (selects `USB_CDC_ACM`, `UART_LINE_CTRL`, etc.; ZMK `app/Kconfig`).
  The snippet's CDC node label is `snippet_zmk_usb_logging_uart`.
- Detection is event-driven: `cdc_acm_dte_rate_callback_set()` fires the
  registered callback on the host's SetLineCoding **rate change**
  (`subsys/usb/device/class/cdc_acm.c`, gated by
  `CONFIG_CDC_ACM_DTE_RATE_CALLBACK_SUPPORT`). We trigger on rate == 1200.
- The nRF52840 Adafruit bootloader does NOT do baud-triggered DFU itself (the
  DTR-auto-reset path is nRF52832-only) — that's why the touch is reproduced in
  the ZMK app. Host-triggered bootloader-over-USB does not exist upstream
  (ZMK issue #2635, closed "not planned").
- HOST GOTCHA: the callback fires on a *change* to 1200. The OS may set the rate
  on first open, so a bare `stty 1200` is a no-op change and won't fire. Prime
  to 9600 then 1200 within one open (see `mac_touch.sh`, `LinuxPlatform.touch_1200`).

## 4. USB serial = chip id
With `CONFIG_HWINFO=y` and a `CONFIG_USB_DEVICE_SN` placeholder, Zephyr overwrites
the serial-number string descriptor from `hwinfo_get_device_id()` at USB init
(`subsys/usb/device/usb_descriptor.c`, `usb_fix_ascii_sn_string_descriptor`).
On nRF52840 that's the FICR.DEVICEID. The Adafruit bootloader independently
exposes the same FICR.DEVICEID as its USB serial (`Adafruit_nRF52_Bootloader
src/usb/usb_desc.c`) — confirmed byte-identical on hardware (e.g.
`8905AEEAAFB95703`). kbd-flash uses this only for calibration/identity, not for
cross-mode matching.

## 5. Split BT bonds + `err 2` (the partner-not-working cause)
`<err> zmk: Security failed: <addr> (random) level 1 err 2` ==
`BT_SECURITY_ERR_PIN_OR_KEY_MISSING` (value 2 in `bt_security_err`,
`include/zephyr/bluetooth/conn.h`). It is logged by the **peripheral**
(`app/src/split/bluetooth/peripheral.c` `security_changed`, ~L127) — so a log
showing it is the peripheral's console, not the central's.

**Why:** the split link is encrypted implicitly — the split GATT characteristics
+ CCCs are `BT_GATT_PERM_*_ENCRYPT` (`app/src/split/bluetooth/service.c`), so when
the central subscribes, the host auto-initiates SMP encryption using the stored
LTK. A bond is a **matched key pair, one record per side**. If only one half was
wiped/reflashed, the half that still has the LTK requests encryption and the
wiped half can't supply it → err 2 → the central never reaches `BT_SECURITY_L2`
(`central.c` gates work on `bt_conn_get_security >= L2`), tears down, rescans,
and loops (the "subscribe → err 2 → unsubscribe → retry" you saw).

**Storage:** bonds persist via `CONFIG_BT_SETTINGS` (ZMK `imply BT_SETTINGS`),
written by `subsys/bluetooth/host/keys.c` (`bt_keys_store`/`bt_keys_clear` →
`bt_settings_{store,delete}_keys`) into the NVS `storage_partition`
(nice_nano.dts `partition@ec000`, 32 KiB @ 0xEC000; Zephyr settings defaults to
the partition labeled `storage`). Erasing that partition (what
`zmk_settings_erase` does) removes the bonds.

**Why BOTH halves:** wiping one side leaves the other with a stale key with no
counterpart → still err 2. Both must be cleared so the next connection has no
key on either side → fresh SMP pairing → new matched LTK pair stored on both.
The settings_reset image disables BLE precisely so the halves don't re-bond
asymmetrically before both are wiped.

**Re-bond (automatic):** after both are cleared and reflashed with real fw,
peripheral advertises (no bonded central), central scans/connects/subscribes,
host does a fresh LE Secure Connections pairing, both store the new bond
(`peripheral.c` `pairing_complete` → `is_bonded`). Power-cycle both together;
no host pairing UI needed. (ZMK also has `CONFIG_ZMK_BLE_CLEAR_BONDS_ON_START`
+ `zmk_ble_clear_all_bonds()` as a lighter alternative to a full NVS wipe.)
Refs: zmk.dev/docs/troubleshooting/connection-issues, features/split-keyboards.

## 6. Boot-count failsafe (`boot_guard.c`)
A `__noinit` counter (survives warm reset, garbage on power-on, magic-validated)
increments each boot; staying up past `WINDOW_MS` clears it via delayed work, so
only RAPID consecutive reboots accumulate. `COUNT` reboots within the window →
`GPREGRET=0x57` + `sys_reboot(0x57)`. Defaults 8 / 10 s, nRF52-only.
Catches: crash/reboot loops + a manual reset-tap escape hatch.
Does NOT catch: a single hang (no reboot) or BLE-load starvation of a *running*
firmware — for that, `settings_reset_touch` (BLE off) is the guaranteed image.

## 7. Recoverability model (what sim covers)
- Sim (native_sim + usbip) proves: USB CDC enumerates, the 1200-baud change
  fires the watcher, and an early POST_KERNEL erase (mirrors `zmk_settings_erase`)
  doesn't strand the device before CDC + watcher come up.
- Sim CANNOT cover: the GPREGRET→UF2 handoff, RAM-retention across reboots
  (boot guard), or real BLE-load timing — those are hardware-only. The
  GPREGRET→UF2 path is hardware-validated separately (5/5).
- Observed robustness lesson: a central in the err-2 retry loop starves USB so
  the touch won't even fire; quieting the partner (BLE off / in bootloader)
  restores it. Mitigation = bring USB up before/independent of BLE + prefer the
  BLE-off settings_reset_touch image for recovery.
