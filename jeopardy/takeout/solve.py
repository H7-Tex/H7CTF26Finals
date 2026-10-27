#!/usr/bin/env python3
# recovered by reading the bytes, no spec given
import struct, zlib, binascii, sys, re, zipfile

PATH = sys.argv[1] if len(sys.argv) > 1 else "takeout.zip"

# zip holds one .kvlt; accept either
if zipfile.is_zipfile(PATH):
    with zipfile.ZipFile(PATH) as z:
        member = next(n for n in z.namelist() if n.endswith(".kvlt"))
        data = z.read(member)
else:
    data = open(PATH, "rb").read()

# 32 byte header: magic, version, flags, count, ts, 16 byte id
assert data[:4] == b"KVLT", "bad magic"
version = data[4]
flags = data[5]
record_count = struct.unpack_from("<H", data, 6)[0]
created = struct.unpack_from("<I", data, 8)[0]
device_id = data[12:28]
app_build = struct.unpack_from("<H", data, 28)[0]

print("magic        KVLT")
print("version     ", version)
print("flags        0x%02x" % flags)
print("records     ", record_count)
print("created      %d" % created)
print("device_id    %s" % device_id.hex())
print("app_build   ", app_build)

# trailing crc32 over everything before it; also confirms field widths
stored_crc = struct.unpack_from("<I", data, len(data) - 4)[0]
calc_crc = binascii.crc32(data[:-4]) & 0xffffffff
print("crc32 stored 0x%08x  calc 0x%08x  %s" %
      (stored_crc, calc_crc, "OK" if stored_crc == calc_crc else "MISMATCH"))
assert stored_crc == calc_crc

# flat type/length/value table after the header
off = 32
end = len(data) - 4
flag = None
while off < end:
    rtype = data[off]
    rlen = struct.unpack_from("<H", data, off + 1)[0]
    value = data[off + 3: off + 3 + rlen]
    off += 3 + rlen

    # value = entry_id + modified, then login fields or (type 0x05) title + blob
    entry_id, modified = struct.unpack_from("<II", value, 0)
    if rtype == 0x05:
        tlen = value[8]
        title = value[9:9 + tlen].decode(errors="replace")
        blob = value[9 + tlen:]
        print("secure note  id=%d title=%r blob=%d bytes" % (entry_id, title, len(blob)))

        # device_id is the only key sized thing; xor gives a zlib stream
        key = device_id
        dec = bytes(b ^ key[i % len(key)] for i, b in enumerate(blob))
        print("  xor[:2]    %s (zlib header)" % dec[:2].hex())
        plain = zlib.decompress(dec).decode(errors="replace")
        m = re.search(r"H7CTF\{[^}]+\}", plain)
        if m:
            flag = m.group(0)
            print("  recovered note:")
            for line in plain.strip().splitlines():
                print("    " + line)

if flag:
    print("\nFLAG:", flag)
else:
    print("\nno flag found")
    sys.exit(1)
