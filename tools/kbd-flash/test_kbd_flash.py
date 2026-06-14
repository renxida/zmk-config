#!/usr/bin/env python3
"""End-to-end tests of the orchestrator against the simulated keyboard pair.

Run: python3 -m unittest -v   (no third-party deps)
"""
from __future__ import annotations

import random
import unittest

from kbd_flash import (
    FlashError,
    Orchestrator,
    Timeouts,
    calibrate_from_devices,
    side_from_product,
)
from kbd_flash import Device
from sim import FaultConfig, SimPlatform, VirtualHalf


FW = {
    "left": "/fw/cradio_left-nice_nano_v2-zmk.uf2",
    "right": "/fw/cradio_right-nice_nano_v2-zmk.uf2",
    "settings_reset": "/fw/settings_reset-nice_nano_v2-zmk.uf2",
}


def make_pair(faults_l=None, faults_r=None, flashed_l="left", flashed_r="right"):
    l = VirtualHalf(chip_id="AAAA1111", true_side="left", flashed_side=flashed_l,
                    faults=faults_l or FaultConfig())
    r = VirtualHalf(chip_id="BBBB2222", true_side="right", flashed_side=flashed_r,
                    faults=faults_r or FaultConfig())
    return l, r


def calib(*halves):
    return {h.chip_id: h.true_side for h in halves}


def orch(plat, calibration, timeouts=None, logs=None):
    return Orchestrator(plat, FW, calibration, timeouts=timeouts,
                        log=(logs.append if logs is not None else None))


class HappyPath(unittest.TestCase):
    def test_both_flash_with_wipe(self):
        l, r = make_pair()
        plat = SimPlatform([l, r])
        res = orch(plat, calib(l, r)).flash_all(wipe_bt=True)
        self.assertEqual(res, {"left": "ok", "right": "ok"})
        for h in (l, r):
            self.assertEqual(h.state, "running")
            self.assertEqual(h.flashed_side, h.true_side)
            self.assertTrue(h.bt_wiped)
            # settings_reset must precede the firmware copy
            copies = [e for e in h.events if e.startswith("copy:")]
            self.assertEqual(len(copies), 2)
            self.assertIn("settings_reset", copies[0])
            self.assertNotIn("settings_reset", copies[1])

    def test_both_flash_no_wipe(self):
        l, r = make_pair()
        plat = SimPlatform([l, r])
        res = orch(plat, calib(l, r)).flash_all(wipe_bt=False)
        self.assertEqual(res, {"left": "ok", "right": "ok"})
        for h in (l, r):
            self.assertFalse(h.bt_wiped)
            self.assertEqual([e for e in h.events if e.startswith("copy:")].__len__(), 1)


class Routing(unittest.TestCase):
    def test_routes_by_chip_id_when_firmware_is_swapped(self):
        # Both halves currently run the WRONG firmware (product strings lie),
        # but calibration maps chip->true side. Must still flash correctly.
        l, r = make_pair(flashed_l="right", flashed_r="left")
        plat = SimPlatform([l, r])
        res = orch(plat, calib(l, r)).flash_all(wipe_bt=False)
        self.assertEqual(res, {"left": "ok", "right": "ok"})
        self.assertEqual(l.flashed_side, "left")
        self.assertEqual(r.flashed_side, "right")

    def test_unknown_chip_ambiguous_product_aborts_preflight(self):
        l, r = make_pair()
        plat = SimPlatform([l, r])
        # empty calibration; product "Cradio L"/"Cradio R" parse fine actually,
        # so force ambiguity by blanking products via a generic flashed side.
        l.flashed_side = r.flashed_side = "x"  # product "Cradio X" -> ambiguous
        with self.assertRaises(FlashError):
            orch(plat, {}).flash_all()
        # nothing should have been touched
        self.assertEqual(l.events, [])
        self.assertEqual(r.events, [])

    def test_product_string_fallback_when_no_calibration(self):
        l, r = make_pair()
        plat = SimPlatform([l, r])
        res = orch(plat, {}).flash_all(wipe_bt=False)  # rely on "Cradio L/R"
        self.assertEqual(res, {"left": "ok", "right": "ok"})

    def test_duplicate_side_aborts(self):
        l = VirtualHalf("AAAA1111", "left", flashed_side="left")
        r = VirtualHalf("BBBB2222", "right", flashed_side="left")
        plat = SimPlatform([l, r])
        with self.assertRaises(FlashError):
            orch(plat, {}).flash_all()


class FailureModes(unittest.TestCase):
    def _one_bad(self, faults_l):
        l, r = make_pair(faults_l=faults_l)
        plat = SimPlatform([l, r])
        logs = []
        res = orch(plat, calib(l, r), logs=logs).flash_all()
        return l, r, res

    def test_dead_cdc_touch_times_out_cleanly(self):
        l, r, res = self._one_bad(FaultConfig(drop_touch=True))
        self.assertTrue(res["left"].startswith("FAILED"))
        self.assertEqual(res["right"], "ok")        # right still succeeds
        self.assertNotEqual(l.flashed_side, "")      # but never wrong-flashed
        self.assertEqual(l.flashed_side, "left")     # untouched -> original

    def test_bricked_flash_times_out_waiting_for_running(self):
        l, r, res = self._one_bad(FaultConfig(brick_on_flash=True))
        self.assertTrue(res["left"].startswith("FAILED"))
        self.assertEqual(res["right"], "ok")

    def test_settings_reset_ignored_times_out(self):
        l, r, res = self._one_bad(FaultConfig(ignore_settings_reset=True))
        self.assertTrue(res["left"].startswith("FAILED"))
        self.assertEqual(res["right"], "ok")

    def test_no_devices_raises(self):
        plat = SimPlatform([])
        with self.assertRaises(FlashError):
            orch(plat, {}).flash_all()


class Serialization(unittest.TestCase):
    def test_only_one_bootloader_at_a_time(self):
        # Instrument discover_bootloaders to assert the invariant continuously.
        l, r = make_pair()
        plat = SimPlatform([l, r])
        max_seen = {"n": 0}
        orig = plat.discover_bootloaders

        def spy():
            vols = orig()
            max_seen["n"] = max(max_seen["n"], len(vols))
            return vols

        plat.discover_bootloaders = spy  # type: ignore
        orch(plat, calib(l, r)).flash_all()
        self.assertLessEqual(max_seen["n"], 1, "two bootloaders visible at once")

    def test_no_cross_contamination(self):
        l, r = make_pair()
        plat = SimPlatform([l, r])
        orch(plat, calib(l, r)).flash_all()
        # left half must never have received right firmware and vice-versa
        self.assertFalse(any("right" in e for e in l.events))
        self.assertFalse(any("left" in e for e in r.events))


class Hardening(unittest.TestCase):
    def test_flap_during_discovery_is_absorbed(self):
        # left half is invisible for the first 3 discovery polls, then appears.
        l, r = make_pair(faults_l=FaultConfig(flap_polls=3))
        plat = SimPlatform([l, r])
        res = orch(plat, calib(l, r)).flash_all(wipe_bt=False)
        self.assertEqual(res, {"left": "ok", "right": "ok"})

    def test_chip_id_collision_raises(self):
        l = VirtualHalf("DUPE", "left", flashed_side="left")
        r = VirtualHalf("DUPE", "right", flashed_side="right")
        plat = SimPlatform([l, r])
        with self.assertRaises(FlashError):
            orch(plat, {}).flash_all()

    def test_stuck_bootloader_no_cross_contamination(self):
        # Regression: left fails (settings_reset ignored) and gets stuck in the
        # bootloader; flashing right must NOT write right's fw to left's volume.
        l, r = make_pair(faults_l=FaultConfig(ignore_settings_reset=True))
        plat = SimPlatform([l, r])
        res = orch(plat, calib(l, r)).flash_all(wipe_bt=True)
        self.assertTrue(res["left"].startswith("FAILED"))
        self.assertEqual(res["right"], "ok")
        # the crux: left half never received right firmware
        self.assertFalse(any("cradio_right" in e for e in l.events),
                         f"left contaminated with right fw: {l.events}")
        self.assertEqual(r.flashed_side, "right")

    def test_single_half_still_works(self):
        # only the left half plugged in -> flash just it, no spurious right wait
        l = VirtualHalf("AAAA1111", "left", flashed_side="left")
        plat = SimPlatform([l])
        res = orch(plat, calib(l)).flash_all(wipe_bt=False)
        self.assertEqual(res, {"left": "ok"})


class Fuzz(unittest.TestCase):
    def test_random_delays_and_faults_preserve_invariants(self):
        trials = 1500
        for seed in range(trials):
            rng = random.Random(seed)
            def rfault():
                # mostly clean; occasionally inject one fault
                f = FaultConfig(
                    t_touch=rng.uniform(0.1, 4.0),
                    t_reset=rng.uniform(0.1, 6.0),
                    t_boot=rng.uniform(0.1, 6.0),
                )
                f.flap_polls = rng.choice([0, 0, 0, 1, 3, 7])
                roll = rng.random()
                if roll < 0.08:
                    f.drop_touch = True
                elif roll < 0.16:
                    f.brick_on_flash = True
                elif roll < 0.22:
                    f.ignore_settings_reset = True
                elif roll < 0.27:
                    f.no_cdc_when_running = True  # never enumerates -> undiscovered
                return f

            l, r = make_pair(faults_l=rfault(), faults_r=rfault())
            # firmware may currently be swapped/unknown
            l.flashed_side = rng.choice(["left", "right"])
            r.flashed_side = rng.choice(["left", "right"])
            plat = SimPlatform([l, r], start=rng.uniform(0, 1000))
            wipe = rng.random() < 0.5
            try:
                res = orch(plat, calib(l, r)).flash_all(wipe_bt=wipe)
            except FlashError:
                # acceptable only when nothing was discoverable at all.
                res = {}
                self.assertEqual(l.events, [], f"seed={seed} l touched then raised")
                self.assertEqual(r.events, [], f"seed={seed} r touched then raised")

            for h, side in ((l, "left"), (r, "right")):
                status = res.get(side)
                msg = f"seed={seed} side={side} events={h.events} res={status}"
                # INVARIANT 1 (always): never flash the wrong side onto a half.
                self.assertFalse(any(s in e for e in h.events
                                     for s in (["right"] if side == "left" else ["left"])
                                     if e.startswith("copy:")), msg)
                if status is None:
                    # never discovered (e.g. no CDC) -> must be wholly untouched.
                    self.assertEqual(h.events, [], msg)
                elif status == "ok":
                    # INVARIANT 2: success => correct fw installed and running.
                    self.assertEqual(h.flashed_side, side, msg)
                    self.assertEqual(h.state, "running", msg)
                    if wipe:
                        self.assertTrue(h.bt_wiped, msg)
                else:
                    # INVARIANT 3: failure is a clean string, not an exception.
                    self.assertTrue(status.startswith("FAILED"), msg)


class Calibration(unittest.TestCase):
    def test_side_from_product(self):
        self.assertEqual(side_from_product("Cradio L"), "left")
        self.assertEqual(side_from_product("Cradio R"), "right")
        self.assertEqual(side_from_product("cradio_left"), "left")
        self.assertIsNone(side_from_product("Cradio"))
        self.assertIsNone(side_from_product(""))
        self.assertIsNone(side_from_product("left or right"))  # both -> ambiguous

    def test_calibrate_happy(self):
        devs = [Device("/d/a", "AAAA", "Cradio L"),
                Device("/d/b", "BBBB", "Cradio R")]
        self.assertEqual(calibrate_from_devices(devs),
                         {"AAAA": "left", "BBBB": "right"})

    def test_calibrate_ambiguous_raises(self):
        with self.assertRaises(FlashError):
            calibrate_from_devices([Device("/d/a", "AAAA", "Cradio")])

    def test_calibrate_duplicate_side_raises(self):
        devs = [Device("/d/a", "AAAA", "Cradio L"),
                Device("/d/b", "BBBB", "Cradio L")]
        with self.assertRaises(FlashError):
            calibrate_from_devices(devs)

    def test_calibrated_map_overrides_lying_product(self):
        # product says right, calibration says left -> trust calibration
        plat = SimPlatform([VirtualHalf("AAAA", "left", flashed_side="right")])
        o = Orchestrator(plat, FW, {"AAAA": "left"})
        self.assertEqual(o.resolve_side(Device("/d/a", "AAAA", "Cradio R")), "left")


class CLI(unittest.TestCase):
    def test_flash_sim_via_main_end_to_end(self):
        import cli
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            for name in ("cradio_left.uf2", "cradio_right.uf2",
                         "settings_reset.uf2"):
                open(f"{d}/{name}", "w").close()
            rc = cli.main(["--sim", "flash", "--no-wipe", "--fw-dir", d,
                           "--calib", "/nonexistent"])
        self.assertEqual(rc, 0)  # sim halves advertise Cradio L/R -> product fallback

    def test_flash_sim_missing_fw_is_clean_error(self):
        import cli
        rc = cli.main(["--sim", "flash", "--fw-dir", "/tmp/definitely-empty-xyz",
                       "--calib", "/nonexistent"])
        self.assertEqual(rc, 1)

    def test_list_sim_via_main(self):
        import cli
        self.assertEqual(cli.main(["--sim", "list"]), 0)

    def test_calibrate_writes_map_via_main(self):
        import cli, json, tempfile, os
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "calib.json")
            rc = cli.main(["--sim", "calibrate", "--out", out])
            self.assertEqual(rc, 0)
            with open(out) as fh:
                m = json.load(fh)
            self.assertEqual(m, {"AAAA1111": "left", "BBBB2222": "right"})

    def test_calibrate_side_guard_with_two_halves(self):
        import cli, tempfile, os
        with tempfile.TemporaryDirectory() as d:
            # sim has two halves; --side expects exactly one -> clean error rc 1
            rc = cli.main(["--sim", "calibrate", "--side", "left",
                           "--out", os.path.join(d, "c.json")])
            self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
