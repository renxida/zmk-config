#!/usr/bin/env python3
"""kbd-flash command-line entrypoint.

  kbd-flash list                 # show halves (running) and bootloaders
  kbd-flash calibrate            # learn chip_id -> side from product strings
  kbd-flash flash [--no-wipe]    # flash both halves the right firmware

By default uses the real Linux platform. --sim runs against the simulator for
a dry demo without hardware.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from kbd_flash import (
    Orchestrator,
    Timeouts,
    calibrate_from_devices,
    find_firmware,
    load_calibration,
)

DEFAULT_CALIB = os.path.expanduser("~/.config/kbd-flash/calibration.json")
DEFAULT_FW_DIR = os.path.expanduser("~/zmk-config/firmware")


def _platform(args):
    if args.sim:
        from sim import SimPlatform, VirtualHalf
        return SimPlatform([
            VirtualHalf("AAAA1111", "left"),
            VirtualHalf("BBBB2222", "right"),
        ])
    from real_platform import LinuxPlatform
    return LinuxPlatform()


def cmd_list(args):
    plat = _platform(args)
    print("running halves:")
    for d in plat.discover_running():
        print(f"  {d.chip_id}  port={d.port}  product={d.product!r}")
    print("bootloader volumes:")
    for v in plat.discover_bootloaders():
        print(f"  {v.chip_id}  mount={v.mount}")
    return 0


def cmd_calibrate(args):
    plat = _platform(args)
    devices = plat.discover_running()
    if not devices:
        print("no running halves found; plug in", file=sys.stderr)
        return 1

    existing = load_calibration(args.out)
    if args.side:
        # one-at-a-time: exactly one half should be connected; record it.
        if len(devices) != 1:
            print(f"--side expects exactly ONE half connected, found {len(devices)}: "
                  f"{[d.chip_id for d in devices]}", file=sys.stderr)
            return 1
        existing[devices[0].chip_id] = args.side
        mapping = existing
        print(f"recorded {devices[0].chip_id} -> {args.side}")
    else:
        # both connected: infer from product strings (needs distinct products).
        learned = calibrate_from_devices(devices)
        existing.update(learned)
        mapping = existing

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(mapping, fh, indent=2)
    print(f"wrote {args.out}:")
    for cid, side in mapping.items():
        print(f"  {cid} -> {side}")
    return 0


def cmd_flash(args):
    plat = _platform(args)
    fw = find_firmware(args.fw_dir)
    missing = [k for k in ("left", "right", "settings_reset") if k not in fw]
    if missing:
        print(f"missing firmware {missing} in {args.fw_dir}", file=sys.stderr)
        return 1
    calib = load_calibration(args.calib)
    orch = Orchestrator(plat, fw, calib, timeouts=Timeouts(), log=lambda m: print(m))
    results = orch.flash_all(wipe_bt=not args.no_wipe, dry_run=args.dry_run)
    print("---")
    rc = 0
    for side, status in sorted(results.items()):
        print(f"{side}: {status}")
        if status not in ("ok", "dry-run"):
            rc = 1
    return rc


def main(argv=None):
    p = argparse.ArgumentParser(prog="kbd-flash")
    p.add_argument("--sim", action="store_true", help="use the simulator")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list").set_defaults(func=cmd_list)

    c = sub.add_parser("calibrate")
    c.add_argument("--out", default=DEFAULT_CALIB)
    c.add_argument("--side", choices=("left", "right"),
                   help="record the single connected half as this side")
    c.set_defaults(func=cmd_calibrate)

    f = sub.add_parser("flash")
    f.add_argument("--no-wipe", action="store_true", help="keep BT bonds")
    f.add_argument("--dry-run", action="store_true",
                   help="show the plan (which fw to which half) without flashing")
    f.add_argument("--fw-dir", default=DEFAULT_FW_DIR)
    f.add_argument("--calib", default=DEFAULT_CALIB)
    f.set_defaults(func=cmd_flash)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
