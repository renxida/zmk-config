/*
 * native_sim harness for usb-bootloader-touch: bring up USB CDC ACM and let
 * the module's watcher thread run. On a host 1200-baud "touch" the watcher
 * logs the trigger (TEST_NO_REBOOT keeps the process alive so the host-side
 * script can observe it).
 */
#include <zephyr/kernel.h>
#include <zephyr/usb/usb_device.h>
#include <zephyr/logging/log.h>

LOG_MODULE_REGISTER(main, LOG_LEVEL_INF);

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
