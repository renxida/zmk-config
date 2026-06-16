#!/usr/bin/env python3
"""Flash a .uf2 to a nice!nano over serial DFU on macOS — no NICENANO mount needed.

Why: after many rapid NICENANO mount cycles, macOS's USB mass-storage / disk
arbitration wedges and the volume stops mounting. Serial DFU flashes over the
Adafruit bootloader's CDC port instead, sidestepping that entirely.

Needs adafruit-nrfutil (see FLASHING.md): ~/.venv-nrfdfu/bin/adafruit-nrfutil
Converts uf2 -> hex (uf2hex.py) -> DFU .zip (genpkg) -> `dfu serial`.

Usage:
  serial_dfu.py <chip_serial> <firmware.uf2>
The half may be in its bootloader (direct DFU) or running a touch-capable app
(auto-adds --touch 1200 to reset it into the bootloader first).
"""
import sys, os, re, subprocess, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
NRF = os.path.expanduser("~/.venv-nrfdfu/bin/adafruit-nrfutil")

def state(ser):
    o1 = subprocess.run("ioreg -p IOUSB -l -w0", shell=True, capture_output=True, text=True).stdout
    prod = {}; cur = None
    for ln in o1.splitlines():
        p = re.search(r'"USB Product Name" = "(.*?)"', ln)
        s = re.search(r'"USB Serial Number" = "([0-9A-Fa-f]{16})"', ln)
        if p: cur = p.group(1)
        if s: prod[s.group(1)] = cur
    o2 = subprocess.run("ioreg -r -c IOUSBHostDevice -l -w0", shell=True, capture_output=True, text=True).stdout
    port = {}; cs = None
    for ln in o2.splitlines():
        s = re.search(r'"USB Serial Number" = "([0-9A-Fa-f]{16})"', ln)
        c = re.search(r'"IOCalloutDevice" = "(/dev/cu\.usbmodem[0-9]+)"', ln)
        if s: cs = s.group(1)
        if c and cs: port[cs] = c.group(1)
    return prod.get(ser, ""), port.get(ser)

def main():
    ser, uf2 = sys.argv[1], sys.argv[2]
    prod, port = state(ser)
    if not port:
        print(f"no CDC port for {ser} (prod={prod!r})"); sys.exit(1)
    td = tempfile.mkdtemp()
    hexf, zipf = f"{td}/fw.hex", f"{td}/fw.zip"
    subprocess.run([sys.executable, f"{HERE}/uf2hex.py", uf2, hexf], check=True)
    subprocess.run([NRF, "dfu", "genpkg", "--dev-type", "0x0052",
                    "--application", hexf, zipf], check=True, capture_output=True)
    # in bootloader -> direct (most reliable); running app -> --touch 1200
    touch = [] if "nice_nano" in prod.lower() else ["--touch", "1200"]
    print(f"serial DFU {ser} ({prod!r}) on {port}  touch={bool(touch)}")
    r = subprocess.run([NRF, "dfu", "serial", "-pkg", zipf, "-p", port,
                        "-b", "115200"] + touch, capture_output=True, text=True)
    ok = "Device programmed" in (r.stdout + r.stderr)
    print(r.stdout.strip()[-400:] if ok else (r.stdout + r.stderr)[-600:])
    # If "No data received": host USB/CDC may be wedged from heavy cycling -> replug.
    sys.exit(0 if ok else 2)

if __name__ == "__main__":
    main()
