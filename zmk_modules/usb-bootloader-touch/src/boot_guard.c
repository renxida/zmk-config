/*
 * Copyright (c) 2026 Cedar Ren
 * SPDX-License-Identifier: MIT
 *
 * Boot-count failsafe: if the firmware reboots COUNT times within WINDOW_MS
 * (a crash loop, or the user deliberately tapping reset), enter the UF2
 * bootloader so the device is always recoverable over USB — even if a future
 * image is broken in a way the touch watcher can't reach.
 *
 * Mechanism: a __noinit counter in RAM survives a warm/soft reset (NVIC reset
 * keeps RAM) but is garbage after power-on; a magic field distinguishes the two.
 * Each boot increments the counter and, if we stay up past WINDOW_MS, a delayed
 * work clears it — so only RAPID consecutive reboots accumulate toward COUNT.
 *
 * NOTE: this catches reboot LOOPS, not a single hang and not BLE-load
 * starvation of a still-running firmware (for that, settings_reset_touch with
 * BLE off is the guaranteed-recoverable image). nRF52 only; uses the same
 * GPREGRET=0x57 + sys_reboot(magic) path as the touch watcher.
 */

#include <zephyr/kernel.h>
#include <zephyr/init.h>
#include <zephyr/sys/reboot.h>
#include <zephyr/logging/log.h>
#include <zephyr/logging/log_ctrl.h>
#include <hal/nrf_power.h>

LOG_MODULE_REGISTER(boot_guard, CONFIG_USB_BOOTLOADER_TOUCH_LOG_LEVEL);

#define BG_MAGIC      0x42477561U /* 'BGua' — validates the __noinit struct */
#define UF2_DFU_MAGIC 0x57U

struct boot_guard_state {
	uint32_t magic;
	uint32_t count;
};

static __noinit struct boot_guard_state bg;

/* Pure predicate, exposed for host-native unit testing. */
bool boot_guard_should_failsafe(uint32_t count, uint32_t threshold)
{
	return count >= threshold;
}

static void bg_clear(struct k_work *work)
{
	ARG_UNUSED(work);
	bg.count = 0;
	LOG_DBG("boot guard: stayed up past window; count cleared");
}
static K_WORK_DELAYABLE_DEFINE(bg_clear_work, bg_clear);

static int boot_guard_init(void)
{
	if (bg.magic != BG_MAGIC) {
		/* Power-on (or post-DFU): __noinit RAM is undefined -> start fresh. */
		bg.magic = BG_MAGIC;
		bg.count = 0;
	}

	bg.count++;
	LOG_INF("boot guard: boot #%u (failsafe at %u within %u ms)", bg.count,
		(unsigned int)CONFIG_USB_BOOTLOADER_TOUCH_BOOT_GUARD_COUNT,
		(unsigned int)CONFIG_USB_BOOTLOADER_TOUCH_BOOT_GUARD_WINDOW_MS);

	if (boot_guard_should_failsafe(bg.count,
				       CONFIG_USB_BOOTLOADER_TOUCH_BOOT_GUARD_COUNT)) {
		LOG_WRN("boot guard: %u rapid reboots -> entering UF2 bootloader",
			bg.count);
		bg.count = 0;
		nrf_power_gpregret_set(NRF_POWER, 0, UF2_DFU_MAGIC);
		LOG_PANIC();
		k_msleep(50);
		sys_reboot(UF2_DFU_MAGIC);
	}

	k_work_schedule(&bg_clear_work,
			K_MSEC(CONFIG_USB_BOOTLOADER_TOUCH_BOOT_GUARD_WINDOW_MS));
	return 0;
}

SYS_INIT(boot_guard_init, APPLICATION, CONFIG_APPLICATION_INIT_PRIORITY);
