/*
 * native_sim harness for usb-bootloader-touch: bring up USB CDC ACM and let
 * the module's watcher thread run. On a host 1200-baud "touch" the watcher
 * logs the trigger (TEST_NO_REBOOT keeps the process alive so the host-side
 * script can observe it).
 */
#include <zephyr/kernel.h>
#include <zephyr/init.h>
#include <zephyr/usb/usb_device.h>
#include <zephyr/logging/log.h>

LOG_MODULE_REGISTER(main, LOG_LEVEL_INF);

/*
 * Recoverability check (mirrors ZMK's settings_reset): an early POST_KERNEL
 * init that "erases" and RETURNS must not strand the device — USB CDC + the
 * touch watcher must still come up afterwards. Same init level/priority (60)
 * as zmk_settings_erase. If this broke the touch path, run_test.sh would fail.
 */
static int mock_settings_erase(void)
{
	LOG_WRN("mock: settings erased at POST_KERNEL (recoverability check)");
	return 0;
}
SYS_INIT(mock_settings_erase, POST_KERNEL, 60);

int main(void)
{
	int ret = usb_enable(NULL);

	if (ret != 0) {
		LOG_ERR("usb_enable failed (%d)", ret);
		return 0;
	}
	LOG_INF("USB enabled; usb-bootloader-touch watcher active");

	/* idle; the watcher runs in its own thread */
	while (true) {
		k_sleep(K_SECONDS(3600));
	}
	return 0;
}
