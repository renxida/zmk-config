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
 * Detection is event-driven via the CDC ACM dwDTERate callback, which fires
 * on the host's SetLineCoding. The watched UART comes from the chosen node
 * `zmk,bootloader-touch-uart` (an overlay points it at the CDC ACM instance,
 * e.g. the zmk-usb-logging console UART).
 *
 * The reboot is deferred to the system workqueue because the rate callback
 * runs in USB control-transfer context.
 */

#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/init.h>
#include <zephyr/drivers/uart/cdc_acm.h>
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
 * Pure predicate, exposed so a host-native unit test can exercise the decision
 * without any Zephyr/USB machinery.
 */
bool usb_bl_touch_baud_matches(uint32_t baud)
{
	return baud == TOUCH_BAUD;
}

static void enter_bootloader_work(struct k_work *work)
{
	ARG_UNUSED(work);

	LOG_WRN("entering UF2 bootloader");

#if IS_ENABLED(CONFIG_RETENTION_BOOT_MODE)
	int ret = bootmode_set(BOOT_MODE_TYPE_BOOTLOADER);

	if (ret < 0) {
		LOG_ERR("bootmode_set failed (%d); not rebooting", ret);
		return;
	}
#else
	/* native_sim / unit builds: no retention HW. */
	LOG_WRN("RETENTION_BOOT_MODE disabled: would enter bootloader (test build)");
	if (IS_ENABLED(CONFIG_USB_BOOTLOADER_TOUCH_TEST_NO_REBOOT)) {
		return;
	}
#endif

	/* Let the host's SetLineCoding ack flush before we drop off the bus. */
	k_msleep(50);
	sys_reboot(SYS_REBOOT_WARM);
}

static K_WORK_DEFINE(bl_work, enter_bootloader_work);

static void on_dte_rate(const struct device *dev, uint32_t rate)
{
	LOG_DBG("host set DTE rate %u on %s", rate, dev->name);

	if (usb_bl_touch_baud_matches(rate)) {
		LOG_WRN("1200-baud touch detected on %s; scheduling bootloader", dev->name);
		k_work_submit(&bl_work);
	}
}

static int usb_bl_touch_init(void)
{
	if (!device_is_ready(touch_uart)) {
		LOG_ERR("touch UART %s not ready; watcher disabled", touch_uart->name);
		return -ENODEV;
	}

	int ret = cdc_acm_dte_rate_callback_set(touch_uart, on_dte_rate);

	if (ret < 0) {
		LOG_ERR("failed to register DTE-rate callback on %s (%d)",
			touch_uart->name, ret);
		return ret;
	}

	LOG_INF("watching %s for %u-baud touch", touch_uart->name, TOUCH_BAUD);
	return 0;
}

SYS_INIT(usb_bl_touch_init, APPLICATION, CONFIG_APPLICATION_INIT_PRIORITY);
