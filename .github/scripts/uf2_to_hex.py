#!/usr/bin/env python3
"""Convert a UF2 image to Intel HEX (stdlib only).

Usage: uf2_to_hex.py <in.uf2> <out.hex>

UF2 is 512-byte blocks; each block header carries a target flash address and a
payload. We emit Intel HEX with Extended Linear Address (type 04) records for
the >64 KiB nRF52840 flash addresses, never crossing a 64 KiB boundary within a
data record.
"""
import struct
import sys

UF2_MAGIC0 = 0x0A324655
UF2_MAGIC1 = 0x9E5D5157


def _ihex(rectype, addr16, data):
    rec = bytes([len(data), (addr16 >> 8) & 0xFF, addr16 & 0xFF, rectype]) + data
    chk = (-sum(rec)) & 0xFF
    return ":" + rec.hex().upper() + format(chk, "02X")


def uf2_to_hex(uf2_path, hex_path):
    blob = open(uf2_path, "rb").read()
    if len(blob) % 512 != 0:
        raise ValueError(f"{uf2_path}: size {len(blob)} not a multiple of 512")

    lines = []
    cur_upper = None
    for i in range(0, len(blob), 512):
        blk = blob[i:i + 512]
        magic0, magic1, _flags, addr, size, _no, _num, _fam = struct.unpack(
            "<IIIIIIII", blk[:32])
        if magic0 != UF2_MAGIC0 or magic1 != UF2_MAGIC1:
            continue  # not a UF2 block
        if size > 476:
            raise ValueError(f"{uf2_path}: bad payload size {size}")
        payload = blk[32:32 + size]

        off = 0
        while off < size:
            a = addr + off
            upper = a >> 16
            if upper != cur_upper:
                lines.append(_ihex(0x04, 0,
                                   bytes([(upper >> 8) & 0xFF, upper & 0xFF])))
                cur_upper = upper
            room = 0x10000 - (a & 0xFFFF)            # stay within this 64 KiB
            chunk = payload[off:off + min(16, room)]
            lines.append(_ihex(0x00, a & 0xFFFF, chunk))
            off += len(chunk)

    lines.append(_ihex(0x01, 0, b""))               # EOF
    with open(hex_path, "w") as fh:
        fh.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: uf2_to_hex.py <in.uf2> <out.hex>")
    uf2_to_hex(sys.argv[1], sys.argv[2])
