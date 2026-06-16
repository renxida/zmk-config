#!/usr/bin/env python3
# Minimal UF2 -> Intel HEX converter (preserves target addresses).
import sys, struct
inp, outp = sys.argv[1], sys.argv[2]
data = open(inp, 'rb').read()
mem = {}
for i in range(0, len(data), 512):
    blk = data[i:i+512]
    if len(blk) < 512: break
    m0, m1 = struct.unpack('<II', blk[0:8])
    if m0 != 0x0A324655 or m1 != 0x9E5D5157: continue
    flags, addr, plen = struct.unpack('<III', blk[8:20])
    for j, b in enumerate(blk[32:32+plen]): mem[addr+j] = b
addrs = sorted(mem)
lines = []
def emit(rtype, off, payload):
    rec = bytes([len(payload), (off>>8)&0xff, off&0xff, rtype]) + payload
    chk = (-sum(rec)) & 0xff
    lines.append(':' + (rec + bytes([chk])).hex().upper())
cur_upper = None; idx = 0; n = len(addrs)
while idx < n:
    start = addrs[idx]; row = [mem[start]]
    while (idx+len(row) < n and addrs[idx+len(row)] == start+len(row)
           and len(row) < 16 and (start>>16) == ((start+len(row))>>16)):
        row.append(mem[addrs[idx+len(row)]])
    upper = (start>>16)&0xffff
    if upper != cur_upper:
        emit(4, 0, struct.pack('>H', upper)); cur_upper = upper
    emit(0, start&0xffff, bytes(row)); idx += len(row)
emit(1, 0, b'')
open(outp, 'w').write('\n'.join(lines)+'\n')
lo, hi = addrs[0], addrs[-1]
print(f"wrote {outp}: {len(mem)} bytes, range 0x{lo:05X}-0x{hi:05X}, {len(lines)} hex records")
