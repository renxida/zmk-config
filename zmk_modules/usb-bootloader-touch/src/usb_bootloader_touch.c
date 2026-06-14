/*
 * Copyright (c) 2026 Cedar Ren
 * SPDX-License-Identifier: MIT
 *
 * usb-bootloader-touch: enter the UF2 bootloader when the USB host opens the
 * CDC ACM port at 1200 baud (the classic Arduino "1200bps touch").
 *
 * Why this exists in the application: on the nRF52840 the Adafruit UF2
 * bootloader enters DFU via double-reset SRAM magic, NOT by watching the CDC
 * baud rate (that path is nRF52832-only). So to get host-triggered bootloader
 * entry over USB we reproduce the Arduino semantic here, in ZMK, and hand off
 * to the same mechanism ZMK's `&bootloader` behavior uses:
 *     bootmode_set(BOOT_MODE_TYPE_BOOTLOADER);  // writes 0x57 -> GPREGRET[0]
 *     sys_reboot(SYS_REBOOT_WARM);
 *
 * The watched UART comes from the chosen node `zmk,bootloader-touch-uart`,
 * which an overlay points at the CDC ACM instance (e.g. the zmk-usb-logging
 * console UART).
 */

#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/drivers/uart.h>
#include <zephyr/sys/reboot.h>
#include <zephyr/logging/log.h>

#if IS_ENABLED(CONFIG_RETENTION_BOOT_MODE)
#include <zephyr/retention/bootmode.h>
#endif

LOG_MODULE_REGISTER(usb_bl_touch, CONFIG_USB_BOOTLOADER_TOUCH_LOG_LEVEL);

#define TOUCH_BAUD 1200U

#define TOUCH_UART_NODE DT_CHOSEN(zmk_bootloader_touch_uart)
BUILD_ASSERT(DT_NODE_HAS_STATUS(TOUCH_UART_NODE, okay),
	     "chosen `zmk,bootloader-touch-uart` must point at an enabled CDC ACM UART");

static const struct device *const touch_uart = DEVICE_DT_GET(TOUCH_UART_NODE);

/*
 * Pure predicate, exposed so the host-native unit test can exercise the
 * decision without any Zephyr/USB machinery.
 */
bool usb_bl_touch_baud_matches(uint32_t baud)
{
	return baud == TOUCH_BAUD;
}

static void usb_bl_touch_enter_bootloader(void)
{
	LOG_WRN("1200-baud touch detected on %s; entering UF2 bootloader", touch_uart->name);

#if IS_ENABLED(CONFIG_RETENTION_BOOT_MODE)
	int ret = bootmode_set(BOOT_MODE_TYPE_BOOTLOADER);

	if (ret < 0) {
		LOG_ERR("bootmode_set failed (%d); not rebooting", ret);
		return;
	}
#else
	/* native_sim / unit builds: no retention HW. Make the trigger observable. */
	LOG_WRN("RETENTION_BOOT_MODE disabled: would enter bootloader (test build)");
	if (IS_ENABLED(CONFIG_USB_BOOTLOADER_TOUCH_TEST_NO_REBOOT)) {
		return;
	}
#endif

	/* Give the host's SetLineCoding ack + our log a moment to flush. */
	k_msleep(50);
	sys_reboot(SYS_REBOOT_WARM);
}

static void usb_bl_touch_thread(void *a, void *b, void *c)
{
	ARG_UNUSED(a);
	ARG_UNUSED(b);
	ARG_UNUSED(c);

	if (!device_is_ready(touch_uart)) {
		LOG_ERR("touch UART %s not ready; watcher disabled", touch_uart->name);
		return;
	}

	uint32_t baud = 0;
	bool armed = true; /* re-arm only after baud leaves 1200, to avoid re-trigger loops */

	LOG_INF("watching %s for %u-baud touch", touch_uart->name, TOUCH_BAUD);

	while (true) {
		if (uart_line_ctrl_get(touch_uart, UART_LINE_CTRL_BAUD_RATE, &baud) == 0) {
			if (armed && usb_bl_touch_baud_matches(baud)) {
				usb_bl_touch_enter_bootloader();
				armed = false;
			} else if (!usb_bl_touch_baud_matches(baud)) {
				armed = true;
			}
		}
		k_msleep(CONFIG_USB_BOOTLOADER_TOUCH_POLL_MS);
	}
}

K_THREAD_DEFINE(usb_bl_touch_tid, CONFIG_USB_BOOTLOADER_TOUCH_STACK_SIZE, usb_bl_touch_thread,
		NULL, NULL, NULL, K_LOWEST_APPLICATION_THREAD_PRIO, 0, 0);
