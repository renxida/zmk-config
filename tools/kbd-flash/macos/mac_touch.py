#!/usr/bin/env python3
"""Reset-free bootloader entry on macOS for usb-bootloader-touch firmware.

Opens the half's USB CDC port and changes the baud 9600 -> 1200. The *change*
to 1200 is what fires the firmware's dwDTERate watcher (plain `stty 1200` does
NOT work on macOS, because the rate is already applied on first open -> no
change). The half then reboots into the UF2 bootloader (NICENANO / serial DFU).

Usage:
  mac_touch.py <chip_serial|/dev/cu.usbmodemXXX>
e.g. mac_touch.py 8905AEEAAFB95703     # by chip serial (resolves the port)
     mac_touch.py /dev/cu.usbmodem1101 # by port

NOTE: the touch will NOT fire if the half is a split central stuck in an
err-2 bond-retry loop (BLE activity starves USB) — quiet the partner first.
"""
import sys, os, time, termios, select, subprocess, re

def port_for_serial(ser):
    out = subprocess.run("ioreg -r -c IOUSBHostDevice -l -w0", shell=True,
                         capture_output=True, text=True).stdout
    cur = None
    for ln in out.splitlines():
        s = re.search(r'"USB Serial Number" = "([0-9A-Fa-f]{16})"', ln)
        c = re.search(r'"IOCalloutDevice" = "(/dev/cu\.usbmodem[0-9]+)"', ln)
        if s: cur = s.group(1)
        if c and cur == ser: return c.group(1)
    return None

def touch(port, hold=1.5):
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    def baud(b):
        a = termios.tcgetattr(fd); a[4] = a[5] = b
        termios.tcsetattr(fd, termios.TCSANOW, a)
    baud(termios.B9600); time.sleep(0.4); baud(termios.B1200)
    end = time.time() + hold
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.3)
        if r:
            try: os.read(fd, 4096)
            except OSError: break  # bus drop == rebooting
    try: os.close(fd)
    except OSError: pass

if __name__ == "__main__":
    arg = sys.argv[1]
    port = arg if arg.startswith("/dev/") else port_for_serial(arg)
    if not port:
        print(f"no CDC port for {arg}"); sys.exit(1)
    print(f"touching {port} (9600->1200)...")
    touch(port)
    print("done — check for NICENANO mount or use serial DFU")
