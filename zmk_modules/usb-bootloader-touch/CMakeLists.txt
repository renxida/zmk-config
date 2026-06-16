# Copyright (c) 2026 Cedar Ren
# SPDX-License-Identifier: MIT

if(CONFIG_USB_BOOTLOADER_TOUCH)
  zephyr_library()
  zephyr_library_sources(src/usb_bootloader_touch.c)
  zephyr_library_sources_ifdef(CONFIG_USB_BOOTLOADER_TOUCH_BOOT_GUARD src/boot_guard.c)
endif()

# ble_name_profile needs ZMK app-internal headers (zmk/ble.h, the event manager,
# zmk_ble_active_profile_index()). Those live on the `app` target's PRIVATE include
# path only — a standalone zephyr_library() can't see them. So compile this file
# INTO `app`, exactly like community ZMK modules do (e.g. zmk-rgbled-widget).
target_sources_ifdef(CONFIG_ZMK_BLE_NAME_PROFILE app PRIVATE src/ble_name_profile.c)
