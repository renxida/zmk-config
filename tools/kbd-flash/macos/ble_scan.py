#!/usr/bin/env python3
"""Scan BLE and print advertised device names (to verify keyboard names on macOS).
Usage: ble_scan.py [seconds]   (needs Bluetooth permission for the running terminal app)"""
import asyncio, sys
from bleak import BleakScanner
KW = ("altair", "vega", "snow", "cradio", "sweep", "ss-")
async def main(secs):
    seen = {}
    def cb(dev, adv):
        nm = adv.local_name or dev.name or ""
        if nm:
            cur = seen.get(dev.address)
            if not cur or adv.rssi > cur[1]: seen[dev.address] = (nm, adv.rssi)
    s = BleakScanner(detection_callback=cb)
    await s.start(); await asyncio.sleep(secs); await s.stop()
    if not seen: print("(no named BLE devices seen — check Bluetooth permission)"); return
    for addr, (nm, rssi) in sorted(seen.items(), key=lambda x: -x[1][1]):
        mark = "  <<< KEYBOARD" if any(k in nm.lower() for k in KW) else ""
        print(f"{rssi:>4} dBm  {nm:<26} {addr}{mark}")
asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 8))
