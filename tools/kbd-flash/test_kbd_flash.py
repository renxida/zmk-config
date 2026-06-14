#!/usr/bin/env python3
"""End-to-end tests of the orchestrator against the simulated keyboard pair.

Run: python3 -m unittest -v   (no third-party deps)
"""
from __future__ import annotations

import random
import unittest

from kbd_flash import FlashError, Orchestrator, Timeouts
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


class Fuzz(unittest.TestCase):
    def test_random_delays_and_faults_preserve_invariants(self):
        trials = 400
        for seed in range(trials):
            rng = random.Random(seed)
            def rfault():
                # mostly clean; occasionally inject one fault
                f = FaultConfig(
                    t_touch=rng.uniform(0.1, 4.0),
                    t_reset=rng.uniform(0.1, 6.0),
                    t_boot=rng.uniform(0.1, 6.0),
                )
                roll = rng.random()
                if roll < 0.08:
                    f.drop_touch = True
                elif roll < 0.16:
                    f.brick_on_flash = True
                elif roll < 0.22:
                    f.ignore_settings_reset = True
                return f

            l, r = make_pair(faults_l=rfault(), faults_r=rfault())
            # firmware may currently be swapped/unknown
            l.flashed_side = rng.choice(["left", "right"])
            r.flashed_side = rng.choice(["left", "right"])
            plat = SimPlatform([l, r], start=rng.uniform(0, 1000))
            wipe = rng.random() < 0.5
            res = orch(plat, calib(l, r)).flash_all(wipe_bt=wipe)

            for h, side in ((l, "left"), (r, "right")):
                msg = f"seed={seed} side={side} events={h.events} res={res[side]}"
                # INVARIANT 1: never flash the wrong side onto a half.
                self.assertFalse(any(s in e for e in h.events
                                     for s in (["right"] if side == "left" else ["left"])
                                     if e.startswith("copy:")), msg)
                if res[side] == "ok":
                    # INVARIANT 2: success => correct fw installed and running.
                    self.assertEqual(h.flashed_side, side, msg)
                    self.assertEqual(h.state, "running", msg)
                    if wipe:
                        self.assertTrue(h.bt_wiped, msg)
                else:
                    # INVARIANT 3: failure is a clean string, not an exception.
                    self.assertTrue(res[side].startswith("FAILED"), msg)


if __name__ == "__main__":
    unittest.main()
