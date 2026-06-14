#!/usr/bin/env python3
"""kbd-flash-all: identify split-keyboard halves by chip ID and flash each the
correct firmware over USB with no physical reset.

The flow leans on two facts established during design:
  * The running ZMK firmware exposes the nRF52840 FICR.DEVICEID as its USB
    serial, and the Adafruit UF2 bootloader exposes the *same* chip ID as its
    serial. So a half keeps one stable identity across running<->bootloader.
  * A `usb-bootloader-touch` firmware feature reboots a half into the UF2
    bootloader when the host opens its CDC port at 1200 baud.

Routing is by chip ID via a calibration map (chip_id -> side); the firmware's
advertised product string is only a fallback. We flash one half at a time
(serialize the touches) so there is never more than one bootloader volume to
disambiguate.

All OS interaction goes through a Platform; the simulator implements the same
interface, so this orchestrator is exercised end-to-end without hardware.
"""
from __future__ import annotations

import abc
import dataclasses
import json
import os
from typing import Callable, Optional


SIDES = ("left", "right")


class FlashError(Exception):
    """Recoverable orchestration failure (timeout, mis-route, unknown chip)."""


@dataclasses.dataclass(frozen=True)
class Device:
    """A half currently enumerated as a running ZMK serial device."""

    port: str
    chip_id: str
    product: str = ""


@dataclasses.dataclass(frozen=True)
class BootVol:
    """A half currently in UF2 bootloader mode (mass-storage mounted)."""

    mount: str
    chip_id: str


class Platform(abc.ABC):
    """Everything the orchestrator needs from the OS, injectable for tests."""

    @abc.abstractmethod
    def discover_running(self) -> list[Device]: ...

    @abc.abstractmethod
    def discover_bootloaders(self) -> list[BootVol]: ...

    @abc.abstractmethod
    def touch_1200(self, port: str) -> None: ...

    @abc.abstractmethod
    def copy_uf2(self, src: str, mount: str) -> None: ...

    @abc.abstractmethod
    def sleep(self, seconds: float) -> None: ...

    @abc.abstractmethod
    def now(self) -> float: ...


@dataclasses.dataclass
class Timeouts:
    bootloader: float = 30.0   # max wait for a half to reach bootloader
    running: float = 45.0      # max wait for a half to re-enumerate running
    unmount: float = 30.0      # max wait for a flash to be accepted (volume gone)
    poll: float = 0.2          # poll interval for all waits


class Orchestrator:
    def __init__(
        self,
        platform: Platform,
        firmware: dict[str, str],
        calibration: dict[str, str],
        timeouts: Optional[Timeouts] = None,
        log: Optional[Callable[[str], None]] = None,
    ):
        # firmware: {'left':path,'right':path,'settings_reset':path}
        missing = [k for k in ("left", "right", "settings_reset") if k not in firmware]
        if missing:
            raise ValueError(f"firmware missing keys: {missing}")
        self.plat = platform
        self.fw = firmware
        self.calib = dict(calibration)  # chip_id -> side
        self.t = timeouts or Timeouts()
        self.log = log or (lambda m: None)

    # --- identity / routing -------------------------------------------------
    def resolve_side(self, dev: Device) -> str:
        """Determine which physical side a device is. Calibration map wins;
        product string is a fallback; otherwise we refuse to guess."""
        if dev.chip_id in self.calib:
            return self.calib[dev.chip_id]
        p = dev.product.lower()
        # Accept "cradio l"/"left"/"-l" style hints, but only if unambiguous.
        is_left = any(s in p for s in (" l", "left", "_l", "-l"))
        is_right = any(s in p for s in (" r", "right", "_r", "-r"))
        if is_left and not is_right:
            return "left"
        if is_right and not is_left:
            return "right"
        raise FlashError(
            f"cannot determine side for chip {dev.chip_id!r} "
            f"(product={dev.product!r}); calibrate first"
        )

    # --- generic wait helper ------------------------------------------------
    def _wait(self, predicate: Callable[[], Optional[object]], timeout: float, what: str):
        deadline = self.plat.now() + timeout
        while True:
            val = predicate()
            if val is not None and val is not False:
                return val
            if self.plat.now() >= deadline:
                raise FlashError(f"timed out after {timeout}s waiting for {what}")
            self.plat.sleep(self.t.poll)

    def _bootloader_for(self, chip_id: str) -> Optional[BootVol]:
        for v in self.plat.discover_bootloaders():
            if v.chip_id == chip_id:
                return v
        return None

    def _running_for(self, chip_id: str) -> Optional[Device]:
        for d in self.plat.discover_running():
            if d.chip_id == chip_id:
                return d
        return None

    # --- per-half flash -----------------------------------------------------
    def flash_one(self, dev: Device, side: str, wipe_bt: bool) -> None:
        cid = dev.chip_id
        self.log(f"[{side}] {cid}: touch 1200 on {dev.port}")
        self.plat.touch_1200(dev.port)

        vol = self._wait(lambda: self._bootloader_for(cid), self.t.bootloader,
                         f"{side} bootloader")

        if wipe_bt:
            self.log(f"[{side}] {cid}: flashing settings_reset (wipe BT)")
            self.plat.copy_uf2(self.fw["settings_reset"], vol.mount)
            self._wait(lambda: self._bootloader_for(cid) is None, self.t.unmount,
                       f"{side} settings_reset to be accepted")
            vol = self._wait(lambda: self._bootloader_for(cid), self.t.bootloader,
                             f"{side} bootloader to return after reset")

        self.log(f"[{side}] {cid}: flashing cradio_{side}")
        self.plat.copy_uf2(self.fw[side], vol.mount)
        self._wait(lambda: self._bootloader_for(cid) is None, self.t.unmount,
                   f"{side} firmware to be accepted")

        run = self._wait(lambda: self._running_for(cid), self.t.running,
                         f"{side} to re-enumerate running")
        got = self.resolve_side(run)
        if got != side:
            raise FlashError(
                f"[{side}] {cid}: post-flash identity is {got!r} — mis-routed!"
            )
        self.log(f"[{side}] {cid}: OK (running, product={run.product!r})")

    # --- top level ----------------------------------------------------------
    def flash_all(self, wipe_bt: bool = True) -> dict[str, str]:
        devices = self.plat.discover_running()
        if not devices:
            raise FlashError("no keyboard halves found over USB")

        # Resolve sides up front so a routing failure aborts before we touch
        # anything (don't leave a half stranded in the bootloader).
        plan: list[tuple[Device, str]] = []
        seen_sides: dict[str, str] = {}
        for d in devices:
            side = self.resolve_side(d)
            if side in seen_sides:
                raise FlashError(
                    f"two devices both resolve to {side!r}: "
                    f"{seen_sides[side]} and {d.chip_id}"
                )
            seen_sides[side] = d.chip_id
            plan.append((d, side))

        results: dict[str, str] = {}
        for dev, side in plan:
            try:
                self.flash_one(dev, side, wipe_bt)
                results[side] = "ok"
            except FlashError as e:
                results[side] = f"FAILED: {e}"
                self.log(str(e))
        return results


# --- firmware discovery ----------------------------------------------------
def find_firmware(fw_dir: str) -> dict[str, str]:
    """Map side -> newest matching .uf2 in fw_dir."""
    out: dict[str, str] = {}
    if not os.path.isdir(fw_dir):
        return out
    files = [f for f in os.listdir(fw_dir) if f.endswith(".uf2")]
    for key, needle in (("left", "left"), ("right", "right"),
                        ("settings_reset", "settings_reset")):
        cands = sorted(
            (f for f in files if needle in f),
            key=lambda f: os.path.getmtime(os.path.join(fw_dir, f)),
            reverse=True,
        )
        if cands:
            out[key] = os.path.join(fw_dir, cands[0])
    return out


def load_calibration(path: str) -> dict[str, str]:
    if path and os.path.exists(path):
        with open(path) as fh:
            return json.load(fh)
    return {}
