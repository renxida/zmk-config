# Copyright (c) 2026 Cedar Ren
# SPDX-License-Identifier: MIT

if(CONFIG_USB_BOOTLOADER_TOUCH)
  zephyr_library()
  zephyr_library_sources(src/usb_bootloader_touch.c)
  zephyr_library_sources_ifdef(CONFIG_USB_BOOTLOADER_TOUCH_BOOT_GUARD src/boot_guard.c)
endif()
