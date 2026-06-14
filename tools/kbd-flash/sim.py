#!/usr/bin/env python3
"""A simulated split-keyboard pair implementing the Platform interface, so the
orchestrator can be exercised end-to-end without hardware.

Each half is a small state machine on a virtual clock:

    running  --touch_1200-->        (gap)  --T_TOUCH-->  bootloader
    bootloader --copy settings_reset--> (gap) --T_RESET--> bootloader (bt wiped)
    bootloader --copy cradio_<side>--> (gap) --T_BOOT-->  running (flashed=<side>)

The "gap" is a transitioning state where neither a serial port nor a mass
storage volume is visible (models the USB re-enumeration window). The virtual
clock only advances when the orchestrator calls sleep(), so tests are fast and
deterministic.
"""
from __future__ import annotations

import dataclasses
from typing import Optional

from kbd_flash import BootVol, Device, Platform


RUNNING = "running"
BOOTLOADER = "bootloader"
GAP = "gap"  # transitioning, nothing enumerated


@dataclasses.dataclass
class FaultConfig:
    """Knobs for fuzzing / failure-mode injection."""

    t_touch: float = 1.0          # delay running->bootloader after touch
    t_reset: float = 3.0          # delay for settings_reset to re-present bootloader
    t_boot: float = 3.0           # delay for firmware to boot to running
    drop_touch: bool = False      # touch silently does nothing (dead CDC)
    brick_on_flash: bool = False  # firmware copy never boots back (bad uf2)
    no_cdc_when_running: bool = False  # running half exposes no serial port
    ignore_settings_reset: bool = False  # settings_reset copy doesn't wipe/re-present


@dataclasses.dataclass
class VirtualHalf:
    chip_id: str
    true_side: str                 # ground-truth physical identity
    state: str = RUNNING
    flashed_side: str = ""         # which fw is installed (advertised when running)
    bt_wiped: bool = False
    faults: FaultConfig = dataclasses.field(default_factory=FaultConfig)
    # pending transition: (effective_time, next_state)
    _pending: Optional[tuple[float, str]] = None
    events: list[str] = dataclasses.field(default_factory=list)

    def __post_init__(self):
        if not self.flashed_side:
            self.flashed_side = self.true_side

    def product(self) -> str:
        return f"Cradio {self.flashed_side[0].upper()}"

    def advance(self, t: float):
        if self._pending and t >= self._pending[0]:
            self.state = self._pending[1]
            self._pending = None


class SimPlatform(Platform):
    def __init__(self, halves: list[VirtualHalf], start: float = 0.0):
        self.halves = halves
        self._t = start

    # clock --------------------------------------------------------------
    def now(self) -> float:
        return self._t

    def sleep(self, seconds: float) -> None:
        self._t += seconds
        for h in self.halves:
            h.advance(self._t)

    def _advance_all(self):
        for h in self.halves:
            h.advance(self._t)

    # discovery ----------------------------------------------------------
    def discover_running(self) -> list[Device]:
        self._advance_all()
        out = []
        for h in self.halves:
            if h.state == RUNNING and not h.faults.no_cdc_when_running:
                out.append(Device(port=f"/dev/sim-{h.chip_id}",
                                   chip_id=h.chip_id, product=h.product()))
        return out

    def discover_bootloaders(self) -> list[BootVol]:
        self._advance_all()
        out = []
        for h in self.halves:
            if h.state == BOOTLOADER:
                out.append(BootVol(mount=f"/sim/NICENANO-{h.chip_id}",
                                   chip_id=h.chip_id))
        return out

    # actions ------------------------------------------------------------
    def _by_port(self, port: str) -> Optional[VirtualHalf]:
        cid = port.rsplit("-", 1)[-1]
        return next((h for h in self.halves if h.chip_id == cid), None)

    def _by_mount(self, mount: str) -> Optional[VirtualHalf]:
        cid = mount.rsplit("-", 1)[-1]
        return next((h for h in self.halves if h.chip_id == cid), None)

    def touch_1200(self, port: str) -> None:
        h = self._by_port(port)
        if h is None or h.state != RUNNING:
            return
        h.events.append("touch")
        if h.faults.drop_touch:
            return
        h.state = GAP
        h._pending = (self._t + h.faults.t_touch, BOOTLOADER)

    def copy_uf2(self, src: str, mount: str) -> None:
        h = self._by_mount(mount)
        if h is None or h.state != BOOTLOADER:
            raise FileNotFoundError(f"no bootloader volume at {mount}")
        base = src.rsplit("/", 1)[-1].lower()
        h.events.append(f"copy:{base}")
        if "settings_reset" in base:
            if h.faults.ignore_settings_reset:
                return  # volume stays; orchestrator will see no unmount -> timeout
            h.bt_wiped = True
            h.state = GAP
            h._pending = (self._t + h.faults.t_reset, BOOTLOADER)
        else:
            # cradio_<side> firmware
            side = "left" if "left" in base else "right" if "right" in base else "?"
            h.flashed_side = side
            if h.faults.brick_on_flash:
                h.state = GAP
                h._pending = None  # never boots back
            else:
                h.state = GAP
                h._pending = (self._t + h.faults.t_boot, RUNNING)
