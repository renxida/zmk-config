#!/usr/bin/env python3
"""Shared helpers for nice!nano / ZMK keyboard diagnostics + flashing on macOS.

Why this exists: enumeration was re-written inline in every script, and zsh's
glob (`/Volumes/NICENANO*` -> "no matches found" aborts the command) kept
breaking mount detection. Everything zsh-glob-sensitive lives here in pure
Python so callers never touch a shell glob.

Pure stdlib — no deps. (BLE bits live in kbd_doctor.py, which needs bleak.)
"""
import glob
import re
import subprocess

# Known chips for Cedar's two pairs (see memory: reference-kbd-hardware).
KNOWN = {
    "8905AEEAAFB95703": ("Altair", "left",  "central"),
    "32AA4109F019FEAF": ("Altair", "right", "peripheral"),
    "EB428AF0E32FB529": ("Vega",   "left",  "central"),
    "56736D74C837B1F9": ("Vega",   "right", "peripheral"),
}


def _ioreg(args):
    return subprocess.run(f"ioreg {args}", shell=True, capture_output=True, text=True).stdout


def devices():
    """All connected nice!nano devices -> list of dicts:
    {serial, product, port, bootloader: bool, pair, side, role}.
    `bootloader` is inferred from the USB product name ("nice_nano" => UF2 DFU).
    """
    # product name <- serial, from the USB device tree
    prod, cur = {}, None
    for ln in _ioreg("-p IOUSB -l -w0").splitlines():
        p = re.search(r'"USB Product Name" = "(.*?)"', ln)
        s = re.search(r'"USB Serial Number" = "([0-9A-Fa-f]{16})"', ln)
        if p:
            cur = p.group(1)
        if s:
            prod[s.group(1).upper()] = cur
    # serial <- callout device (CDC port)
    port, cs = {}, None
    for ln in _ioreg("-r -c IOUSBHostDevice -l -w0").splitlines():
        s = re.search(r'"USB Serial Number" = "([0-9A-Fa-f]{16})"', ln)
        c = re.search(r'"IOCalloutDevice" = "(/dev/cu\.usbmodem[0-9]+)"', ln)
        if s:
            cs = s.group(1).upper()
        if c and cs:
            port[cs] = c.group(1)
    out = []
    for ser, pname in prod.items():
        pair, side, role = KNOWN.get(ser, ("?", "?", "?"))
        bl = bool(pname and "nice_nano" in pname.lower())
        out.append({"serial": ser, "product": pname or "", "port": port.get(ser),
                    "bootloader": bl, "pair": pair, "side": side, "role": role})
    return out


def port_for(serial):
    serial = serial.upper()
    for d in devices():
        if d["serial"] == serial:
            return d["port"]
    return None


def nicenano_volume():
    """Path to a mounted NICENANO* volume, or None. Pure glob (zsh-safe)."""
    v = glob.glob("/Volumes/NICENANO*")
    return v[0] if v else None


def bootloader_serial():
    """Chip serial of a device currently in the UF2 bootloader, or None."""
    for d in devices():
        if d["bootloader"]:
            return d["serial"]
    return None


if __name__ == "__main__":
    for d in devices():
        tag = "BOOTLOADER" if d["bootloader"] else "app"
        print(f"{d['serial']}  {d['pair']:6} {d['side']:5} {d['role']:10} "
              f"{tag:10} port={d['port'] or '-':18} '{d['product']}'")
