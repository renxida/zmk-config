#!/usr/bin/env python3
import subprocess, re
out = subprocess.run("ioreg -r -c IOUSBHostDevice -l -w0", shell=True, capture_output=True, text=True).stdout
cur = None
for ln in out.splitlines():
    s = re.search(r'"USB Serial Number" = "([0-9A-Fa-f]{16})"', ln)
    c = re.search(r'"IOCalloutDevice" = "(/dev/cu\.usbmodem[0-9]+)"', ln)
    if s: cur = s.group(1)
    if c and cur: print(cur, c.group(1))
