#!/usr/bin/env python3
"""kbd_doctor — autonomous BT / battery / split diagnostics for the Cradio pairs.

Run with the bleak venv for BLE features:  ~/.venv-ble/bin/python3 kbd_doctor.py ...
(enum / splitlog work on plain python3 too; scan / battery need bleak.)

Commands:
  enum                          list connected nice!nano devices + state
  scan [secs=8]                 BLE scan; flags keyboards, sorted by RSSI
  splitlog <serial|pair> [secs] capture central USB-CDC log, parse split health
  battery [name=Vega] [secs=8]  connect over BLE, read Battery Service level(s)
  flash <serial|pair-side> <uf2>  touch->bootloader->flash (MSC|serial DFU)->verify
  health [pair=Vega]            full report (enum + scan + splitlog + battery)

Design notes / gotchas baked in:
  * BLE scan has a hard asyncio timeout + guaranteed stop -> never hangs the run
    (CoreBluetooth occasionally wedges; we bound it).
  * CDC capture reads raw bytes via a non-blocking fd + select, decodes
    errors='replace', strips ANSI in Python -> no `sed: illegal byte sequence`.
  * All USB/volume enumeration goes through kbd_lib (no zsh globs).
  * battery CONNECTS to the keyboard (consumes a BLE profile slot / may bond).
    Safe on Vega (test pair); do NOT point it at a keyboard you can't re-pair.
"""
import asyncio
import os
import re
import select
import subprocess
import sys
import time

import kbd_lib

BAS_LEVEL_UUID = "00002a19-0000-1000-8000-00805f9b34fb"  # Battery Level (0x2A19)
KW = ("altair", "vega", "snow", "cradio", "sweep", "ss-")
ANSI = re.compile(rb"\x1b\[[0-9;]*m")


# ---------- USB enumeration ----------
def cmd_enum(_args):
    ds = kbd_lib.devices()
    if not ds:
        print("(no nice!nano devices connected)")
        return
    for d in ds:
        tag = "BOOTLOADER" if d["bootloader"] else "app"
        print(f"{d['serial']}  {d['pair']:6} {d['side']:5} {d['role']:10} "
              f"{tag:10} port={d['port'] or '-':20} '{d['product']}'")


def _central_serial(token):
    """Resolve a 'serial' or pair-name token to a central chip serial."""
    token = token.strip()
    if re.fullmatch(r"[0-9A-Fa-f]{16}", token):
        return token.upper()
    for ser, (pair, _side, role) in kbd_lib.KNOWN.items():
        if pair.lower() == token.lower() and role == "central":
            return ser
    return None


# ---------- CDC log capture (split health) ----------
def capture_cdc(port, secs):
    """Read a CDC port for `secs`, re-opening on EOF. Returns decoded text."""
    buf = bytearray()
    deadline = time.time() + secs
    while time.time() < deadline:
        try:
            fd = os.open(port, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            time.sleep(0.3)
            continue
        try:
            while time.time() < deadline:
                r, _, _ = select.select([fd], [], [], 0.5)
                if not r:
                    continue
                try:
                    chunk = os.read(fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
        finally:
            os.close(fd)
    return ANSI.sub(b"", bytes(buf)).decode("utf-8", "replace")


def cmd_splitlog(args):
    if not args:
        print("usage: splitlog <serial|pair> [secs]")
        return
    ser = _central_serial(args[0])
    secs = int(args[1]) if len(args) > 1 else 12
    if not ser:
        print(f"could not resolve '{args[0]}' to a central serial")
        return
    port = kbd_lib.port_for(ser)
    print(f"central {ser} -> port {port or 'NONE'} ; capturing {secs}s")
    if not port:
        print("  central not enumerated (unplugged or in bootloader)")
        return
    txt = capture_cdc(port, secs)
    lines = txt.splitlines()
    print(f"  captured {len(txt)} bytes, {len(lines)} lines")
    pat = re.compile(r"subscrib|security|err [0-9]|level|disconnect|"
                     r"split_central.*found|peripheral|bonded|name set|BLE name", re.I)
    hits = [ln for ln in lines if pat.search(ln)]
    for ln in hits[-18:]:
        print("   ", ln.strip())
    # verdict. Distinguish the real split fault (err 2 = bond mismatch between the
    # two halves) from benign host churn (err 9 / reason 0x13 = an unbonded BLE
    # client like a battery read connecting then being dropped — NOT a split issue).
    blob = txt.lower()
    sub = "subscribed" in blob
    err2 = bool(re.search(r"\berr 2\b", blob)) or "pin_or_key_missing" in blob
    host_churn = bool(re.search(r"\berr 9\b", blob)) or "reason 0x13" in blob
    if err2:
        verdict = "BROKEN — err 2 bond mismatch between halves (settings_reset BOTH + reflash + re-pair)"
    elif sub:
        verdict = "CONNECTED — peripheral [SUBSCRIBED]"
    elif not lines:
        verdict = "no log output (idle/already booted) — capture right after a replug to see the handshake"
    else:
        verdict = "no fresh handshake in window (central booted earlier; not necessarily broken)"
    if host_churn and not err2:
        verdict += "  [saw benign host connect/disconnect — e.g. a battery read; ignore for split health]"
    print(f"  VERDICT: {verdict}")


# ---------- BLE scan ----------
async def _scan(secs):
    from bleak import BleakScanner
    seen = {}

    def cb(dev, adv):
        nm = adv.local_name or dev.name or ""
        if nm:
            cur = seen.get(dev.address)
            if not cur or adv.rssi > cur[1]:
                seen[dev.address] = (nm, adv.rssi)

    s = BleakScanner(detection_callback=cb)
    await s.start()
    try:
        await asyncio.sleep(secs)
    finally:
        try:
            await s.stop()
        except Exception:
            pass
    return seen


def cmd_scan(args):
    secs = int(args[0]) if args else 8
    try:
        seen = asyncio.run(asyncio.wait_for(_scan(secs), timeout=secs + 8))
    except asyncio.TimeoutError:
        print("(scan timed out — CoreBluetooth wedge; re-run)")
        return
    if not seen:
        print("(no named BLE devices — check Bluetooth permission for the terminal)")
        return
    for addr, (nm, rssi) in sorted(seen.items(), key=lambda x: -x[1][1]):
        mark = "  <<< KEYBOARD" if any(k in nm.lower() for k in KW) else ""
        print(f"{rssi:>4} dBm  {nm:<28} {addr}{mark}")


# ---------- BLE battery ----------
async def _battery(name, secs):
    from bleak import BleakClient, BleakScanner
    target = None
    found = {}

    def cb(dev, adv):
        nm = adv.local_name or dev.name or ""
        if nm:
            found[dev.address] = (nm, adv.rssi)

    s = BleakScanner(detection_callback=cb)
    await s.start()
    try:
        for _ in range(int(secs * 2)):
            await asyncio.sleep(0.5)
            for addr, (nm, _r) in found.items():
                if name.lower() in nm.lower():
                    target = (addr, nm)
                    break
            if target:
                break
    finally:
        await s.stop()
    if not target:
        return None, f"no advertising device matching '{name}'"
    addr, nm = target
    try:
        async with BleakClient(addr, timeout=20) as cli:
            results = []
            for svc in cli.services:
                for ch in svc.characteristics:
                    if ch.uuid.lower() == BAS_LEVEL_UUID and "read" in ch.properties:
                        val = await cli.read_gatt_char(ch.uuid)
                        results.append((svc.handle, int(val[0])))
            return (nm, addr, results), None
    except Exception as e:
        return None, f"connect/read failed for {nm} ({addr}): {e!r}"


def cmd_battery(args):
    name = args[0] if args else "Vega"
    secs = int(args[1]) if len(args) > 1 else 8
    print(f"searching for '{name}' and reading Battery Service... "
          f"(connects -> may consume a BLE profile slot)")
    res, err = asyncio.run(_battery(name, secs))
    if err:
        print("  " + err)
        return
    nm, addr, levels = res
    if not levels:
        print(f"  connected to {nm} ({addr}) but no readable Battery Level char "
              f"(BAS absent or encryption-gated)")
        return
    for handle, pct in levels:
        print(f"  {nm}: battery {pct}%  (service handle {handle})")
    print("  note: % is a voltage estimate; reads high while on USB power.")


def _resolve_target(token):
    """'<16-hex serial>' or '<pair>-<side>' (e.g. vega-left) -> chip serial."""
    token = token.strip()
    if re.fullmatch(r"[0-9A-Fa-f]{16}", token):
        return token.upper()
    m = re.fullmatch(r"([A-Za-z]+)-(left|right)", token, re.I)
    if m:
        pair, side = m.group(1).lower(), m.group(2).lower()
        for ser, (p, s, _role) in kbd_lib.KNOWN.items():
            if p.lower() == pair and s == side:
                return ser
    return None


def _wait(pred, secs, every=0.7):
    deadline = time.time() + secs
    while time.time() < deadline:
        v = pred()
        if v:
            return v
        time.sleep(every)
    return None


def cmd_flash(args):
    """flash <serial|pair-side> <firmware.uf2> — touch->bootloader->flash->verify.

    One-shot, recoverable, hands-free. Touches the running half to the UF2
    bootloader, WAITS for it to actually enumerate (fixes the serial_dfu auto-
    touch race), then flashes via MSC if NICENANO mounts else serial DFU, and
    finally waits for the app to come back.
    """
    if len(args) < 2:
        print("usage: flash <serial|pair-side> <firmware.uf2>")
        return
    import shutil
    here = os.path.dirname(os.path.abspath(__file__))
    ser = _resolve_target(args[0])
    fw = os.path.abspath(os.path.expanduser(args[1]))
    if not ser:
        print(f"could not resolve target '{args[0]}'")
        return
    if not os.path.isfile(fw):
        print(f"no such firmware: {fw}")
        return
    pair, side, role = kbd_lib.KNOWN.get(ser, ("?", "?", "?"))
    print(f"FLASH target {ser} ({pair} {side} {role}) <- {os.path.basename(fw)}")

    if kbd_lib.bootloader_serial() != ser:
        port = kbd_lib.port_for(ser)
        if not port:
            print("  target not enumerated as app or bootloader; abort")
            return
        print(f"  touching {port} -> bootloader ...")
        subprocess.run(["python3", os.path.join(here, "mac_touch.py"), ser],
                       capture_output=True, text=True)
        if not _wait(lambda: kbd_lib.bootloader_serial() == ser, 25):
            print("  target did not enter bootloader within 25s; abort")
            return
    print("  in bootloader ✓")
    # Wait for a usable flash channel — the bootloader's MSC volume and CDC port
    # take a moment to enumerate after the USB device appears. Flashing before
    # then is the serial_dfu auto-touch race; this is the fix.
    _wait(lambda: kbd_lib.nicenano_volume() or kbd_lib.port_for(ser), 12)

    vol = kbd_lib.nicenano_volume()
    flashed = False
    if vol and kbd_lib.bootloader_serial() == ser:
        print(f"  MSC copy -> {vol}")
        try:
            shutil.copy(fw, vol + "/")
        except Exception as e:
            print(f"    (copy raised, normal if it reset mid-copy: {e})")
        flashed = True
    else:
        print("  no NICENANO mount (USB wedge?) -> serial DFU (direct)")
        r = subprocess.run(["python3", os.path.join(here, "serial_dfu.py"), ser, fw],
                           capture_output=True, text=True)
        ok = "Device programmed" in (r.stdout + r.stderr)
        print("    serial DFU:", "OK" if ok else "FAILED")
        print("   ", (r.stdout + r.stderr).strip().splitlines()[-1] if (r.stdout or r.stderr) else "")
        flashed = ok
    if not flashed:
        print("  FLASH FAILED")
        return
    app = _wait(lambda: next((d for d in kbd_lib.devices()
                              if d["serial"] == ser and not d["bootloader"]), None), 25)
    print(f"  app back ✓ ('{app['product']}')" if app else "  (app not seen yet — give it a moment)")


def cmd_health(args):
    pair = args[0] if args else "Vega"
    print("=" * 56, "\nUSB DEVICES\n" + "=" * 56)
    cmd_enum([])
    print("=" * 56, "\nBLE SCAN\n" + "=" * 56)
    cmd_scan(["8"])
    print("=" * 56, f"\nSPLIT HEALTH ({pair} central)\n" + "=" * 56)
    cmd_splitlog([pair, "10"])
    print("=" * 56, f"\nBATTERY ({pair})\n" + "=" * 56)
    cmd_battery([pair])


CMDS = {"enum": cmd_enum, "scan": cmd_scan, "splitlog": cmd_splitlog,
        "battery": cmd_battery, "flash": cmd_flash, "health": cmd_health}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in CMDS:
        print(__doc__)
        sys.exit(0 if len(sys.argv) < 2 else 2)
    CMDS[sys.argv[1]](sys.argv[2:])
