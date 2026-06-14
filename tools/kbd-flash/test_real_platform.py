#!/usr/bin/env python3
"""Unit tests for the Linux platform's pure parsers (no hardware needed)."""
from __future__ import annotations

import unittest

from real_platform import (
    bootvols_from_lsblk,
    device_from_udev,
    parse_udev_properties,
)


UDEV_RUNNING = """\
DEVNAME=/dev/ttyACM0
ID_BUS=usb
ID_MODEL=Cradio_L
ID_MODEL_ID=0029
ID_SERIAL=ZMK_Project_Cradio_L_E1A2B3C4D5E6F708
ID_SERIAL_SHORT=E1A2B3C4D5E6F708
ID_VENDOR=ZMK_Project
ID_USB_INTERFACE_NUM=00
"""

UDEV_NONKBD = """\
DEVNAME=/dev/ttyACM1
ID_BUS=usb
ID_MODEL=USB_Serial
ID_SERIAL=FTDI_USB_Serial_ABCD
ID_SERIAL_SHORT=ABCD
ID_VENDOR=FTDI
"""

LSBLK = """\
{"blockdevices":[
  {"name":"vda","label":null,"mountpoint":null,"serial":"do-vol","type":"disk",
   "children":[{"name":"vda1","label":"cloudimg","mountpoint":"/","serial":null,"type":"part"}]},
  {"name":"sda","label":null,"mountpoint":null,"serial":"E1A2B3C4D5E6F708","type":"disk",
   "children":[{"name":"sda1","label":"NICENANO","mountpoint":"/media/cedar/NICENANO","serial":null,"type":"part"}]}
]}
"""


class ParseUdev(unittest.TestCase):
    def test_properties(self):
        p = parse_udev_properties(UDEV_RUNNING)
        self.assertEqual(p["ID_SERIAL_SHORT"], "E1A2B3C4D5E6F708")
        self.assertEqual(p["ID_MODEL"], "Cradio_L")

    def test_device_from_udev_matches_keyboard(self):
        p = parse_udev_properties(UDEV_RUNNING)
        dev = device_from_udev("/dev/ttyACM0", p)
        self.assertIsNotNone(dev)
        self.assertEqual(dev.chip_id, "E1A2B3C4D5E6F708")
        self.assertEqual(dev.product, "Cradio_L")

    def test_device_from_udev_rejects_non_keyboard(self):
        p = parse_udev_properties(UDEV_NONKBD)
        self.assertIsNone(device_from_udev("/dev/ttyACM1", p))


class ParseLsblk(unittest.TestCase):
    def test_finds_nicenano_with_chip_id(self):
        vols = bootvols_from_lsblk(LSBLK)
        self.assertEqual(len(vols), 1)
        self.assertEqual(vols[0].mount, "/media/cedar/NICENANO")
        # partition serial is null -> blank, to be backfilled from parent
        self.assertEqual(vols[0].chip_id, "")

    def test_ignores_root_and_unmounted(self):
        vols = bootvols_from_lsblk(LSBLK)
        self.assertTrue(all("NICENANO" in v.mount for v in vols))


if __name__ == "__main__":
    unittest.main()
