/*
 * Copyright (c) 2026 Cedar Ren
 * SPDX-License-Identifier: MIT
 *
 * ble-name-profile: set the advertised BLE device name to "<base>-P<profile>"
 * on boot and on every active-profile change. Two purposes:
 *   1. The host's "pair new device" list shows which profile you're on — a host
 *      paired while on profile 2 caches "<base>-P2" (a persistent per-host label).
 *   2. Because it *writes* the name every boot, it overrides any stale name
 *      persisted in NVS (the "bt/name" dynamic-name entry) — so a firmware
 *      reflash actually changes the name, without a settings_reset / re-pair.
 *
 * <base> is CONFIG_BT_DEVICE_NAME (which ZMK derives from CONFIG_ZMK_KEYBOARD_NAME,
 * stamped with the build hash). Keep CONFIG_BT_DEVICE_NAME_MAX large enough for
 * "<base>-P<n>".
 */
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/init.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <stdio.h>
#include <string.h>

#include <zmk/ble.h>
#include <zmk/event_manager.h>
#include <zmk/events/ble_active_profile_changed.h>

LOG_MODULE_REGISTER(ble_name_profile, CONFIG_ZMK_LOG_LEVEL);

static void apply_name(void) {
    char buf[CONFIG_BT_DEVICE_NAME_MAX + 1];
    int idx = zmk_ble_active_profile_index();
    snprintf(buf, sizeof(buf), "%s-P%d", CONFIG_BT_DEVICE_NAME, idx);
    const char *cur = bt_get_name();
    if (cur && strcmp(cur, buf) == 0) {
        return; /* already correct — avoid a redundant NVS write + adv restart */
    }
    /* Must use ZMK's setter, not bare bt_set_name(): ZMK advertises with
     * BT_LE_ADV_OPT_USE_NAME, so the name is baked into the AD packet at
     * adv-start. zmk_ble_set_device_name() does bt_set_name() THEN stops and
     * restarts advertising (update_advertising), so the scanner actually sees
     * the new name. Bare bt_set_name() updates only the GAP name -> stale AD. */
    int rc = zmk_ble_set_device_name(buf);
    LOG_WRN("BLE name set to '%s' (was '%s', rc %d)", buf, cur ? cur : "(null)", rc);
}

/* Re-apply whenever the active profile changes. */
static int on_profile_changed(const zmk_event_t *eh) {
    apply_name();
    return ZMK_EV_EVENT_BUBBLE;
}
ZMK_LISTENER(ble_name_profile, on_profile_changed);
ZMK_SUBSCRIPTION(ble_name_profile, zmk_ble_active_profile_changed);

/* Initial set, deferred until BLE + settings are up (bt_set_name needs bt_enable). */
static void initial_work(struct k_work *work) {
    ARG_UNUSED(work);
    apply_name();
}
static K_WORK_DELAYABLE_DEFINE(initial_dwork, initial_work);

static int ble_name_profile_init(void) {
    k_work_schedule(&initial_dwork, K_SECONDS(2));
    return 0;
}
SYS_INIT(ble_name_profile_init, APPLICATION, 99);
