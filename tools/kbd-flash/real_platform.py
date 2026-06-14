#!/usr/bin/env python3
"""Linux implementation of Platform for real hardware.

The OS-interaction is split into thin live wrappers (subprocess calls) and pure
parsers. Only the parsers are unit-tested here — the live calls need a keyboard
plugged in, which is the part we verify with you on the bench.

Identity model (must match the firmware/bootloader):
  * running ZMK  -> /dev/ttyACM*  whose udev ID_SERIAL_SHORT == FICR.DEVICEID
  * UF2 bootloader -> a FAT volume labelled NICENANO whose backing USB device
    serial == the same FICR.DEVICEID (Adafruit bootloader publishes it).
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Optional

from kbd_flash import BootVol, Device, Platform


# Our keyboard's USB ids. ZMK defaults: VID 1d50 / PID 615e. The UF2 bootloader
# (Adafruit nRF) is VID 239a. Product hints are a softer secondary signal.
ZMK_VID = "1d50"
ZMK_PID = "615e"
ZMK_PRODUCT_HINTS = ("cradio", "zmk", "ss")
BOOTLOADER_LABELS = ("NICENANO", "NICE!NANO")


# --- pure parsers (unit-tested) -------------------------------------------
def parse_udev_properties(text: str) -> dict[str, str]:
    """Parse `udevadm info -q property` KEY=VALUE lines."""
    props: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        k, _, v = line.partition("=")
        props[k] = v
    return props


def device_from_udev(devnode: str, props: dict[str, str]) -> Optional[Device]:
    """Build a Device from udev props if it looks like one of our halves.
    Primary signal is the ZMK USB VID; product-string hints are a fallback for
    when the VID was customised."""
    chip = props.get("ID_SERIAL_SHORT")
    if not chip:
        return None
    product = props.get("ID_MODEL", "") or props.get("ID_MODEL_FROM_DATABASE", "")
    vid = (props.get("ID_VENDOR_ID") or props.get("ID_USB_VENDOR_ID") or "").lower()
    if vid == ZMK_VID:
        return Device(port=devnode, chip_id=chip, product=product)
    blob = " ".join([
        product, props.get("ID_SERIAL", ""), props.get("ID_VENDOR", "")
    ]).lower()
    if any(h in blob for h in ZMK_PRODUCT_HINTS):
        return Device(port=devnode, chip_id=chip, product=product)
    return None


def bootvols_from_lsblk(lsblk_json: str) -> list[BootVol]:
    """Parse `lsblk -J -o NAME,LABEL,MOUNTPOINT,SERIAL,TYPE` for UF2 volumes."""
    data = json.loads(lsblk_json)
    out: list[BootVol] = []

    def walk(node):
        label = (node.get("label") or "").upper()
        mnt = node.get("mountpoint")
        serial = node.get("serial") or ""
        if any(b in label for b in BOOTLOADER_LABELS) and mnt:
            # lsblk SERIAL on the partition may be empty; caller can backfill
            # the chip id from the parent USB device serial.
            out.append(BootVol(mount=mnt, chip_id=serial))
        for child in node.get("children", []) or []:
            walk(child)

    for dev in data.get("blockdevices", []):
        walk(dev)
    return out


# --- live platform ---------------------------------------------------------
class LinuxPlatform(Platform):
    def __init__(self, run=None):
        self._run = run or self._default_run

    @staticmethod
    def _default_run(cmd: list[str], **kw) -> str:
        return subprocess.run(cmd, capture_output=True, text=True, **kw).stdout

    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def discover_running(self) -> list[Device]:
        out: list[Device] = []
        by_id = "/dev/serial/by-id"
        nodes = []
        if os.path.isdir(by_id):
            nodes = [os.path.realpath(os.path.join(by_id, e))
                     for e in os.listdir(by_id)]
        else:
            nodes = ["/dev/" + e for e in os.listdir("/dev")
                     if e.startswith("ttyACM")]
        for node in sorted(set(nodes)):
            props = parse_udev_properties(
                self._run(["udevadm", "info", "-q", "property", "-n", node]))
            dev = device_from_udev(node, props)
            if dev:
                out.append(dev)
        return out

    def discover_bootloaders(self) -> list[BootVol]:
        vols = bootvols_from_lsblk(
            self._run(["lsblk", "-J", "-o", "NAME,LABEL,MOUNTPOINT,SERIAL,TYPE"]))
        # Backfill chip id from the USB device serial when the partition serial
        # is blank (common): walk the block device's udev parent.
        filled = []
        for v in vols:
            cid = v.chip_id
            if not cid:
                cid = self._chip_id_for_mount(v.mount)
            filled.append(BootVol(mount=v.mount, chip_id=cid))
        return filled

    def _chip_id_for_mount(self, mount: str) -> str:
        # findmnt -> source device -> udev ID_SERIAL_SHORT
        src = self._run(["findmnt", "-n", "-o", "SOURCE", mount]).strip()
        if not src:
            return ""
        props = parse_udev_properties(
            self._run(["udevadm", "info", "-q", "property", "-n", src]))
        return props.get("ID_SERIAL_SHORT", "")

    def touch_1200(self, port: str) -> None:
        # The firmware watcher fires on a baud *change* to 1200. The OS may set
        # the rate on first open, so a bare "set 1200" can be a no-op change.
        # Prime to 9600 first, then 1200, within a single open. stdlib termios.
        import termios
        fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            attrs = termios.tcgetattr(fd)
            for speed in (termios.B9600, termios.B1200):
                attrs[4] = speed  # ispeed
                attrs[5] = speed  # ospeed
                termios.tcsetattr(fd, termios.TCSANOW, attrs)
                time.sleep(0.2)
        finally:
            os.close(fd)

    def copy_uf2(self, src: str, mount: str) -> None:
        import shutil
        dst = os.path.join(mount, os.path.basename(src))
        try:
            shutil.copy(src, dst)
            fd = os.open(mount, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            # The bootloader reboots mid-copy and yanks the volume; that's the
            # normal success signal, not a failure.
            pass
