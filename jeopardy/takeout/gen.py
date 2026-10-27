#!/usr/bin/env python3
# author-only. builds the shipped handout. not given to players.
# container format (little endian), invented for this challenge:
#
#   header (32 bytes)
#     0:4   magic        b"KVLT"
#     4     version      0x02
#     5     flags        bit0 = vault contains secure notes
#     6:8   record_count uint16
#     8:12  created      uint32 unix seconds
#     12:28 device_id    16 bytes  (per install fingerprint, doubles as the note key)
#     28:30 app_build    uint16
#     30:32 reserved     0x0000
#
#   record_count records, each:
#     1     rtype        0x01 login entry, 0x05 secure note
#     2     rlen         uint16  length of value
#     rlen  value
#
#   login entry value:
#     entry_id uint32, modified uint32, then 5 length prefixed fields
#       title, username, password, url, memo   (1 byte length each)
#
#   secure note value:
#     entry_id uint32, modified uint32, title (1 byte length prefix),
#     blob = xor(zlib(note_text), device_id repeating)
#
#   trailer
#     4     crc32 over every byte before it, little endian

import struct, zlib, binascii, datetime, zipfile

OUT = "keyvault-backup-20241029.kvlt"
ZIP = "takeout.zip"

FLAG = "H7CTF{23bd9cba0f4cde4b9b253db080ecc51e}"

DEVICE_ID = bytes.fromhex("9f2c71a40be85d3348c6e0f71b9a2d55")
APP_BUILD = 2411
CREATED = int(datetime.datetime(2024, 10, 29, 9, 14, 56, tzinfo=datetime.timezone.utc).timestamp())


def ts(y, mo, d, h, mi):
    return int(datetime.datetime(y, mo, d, h, mi, tzinfo=datetime.timezone.utc).timestamp())


def lp(b):
    # 1 byte length prefix
    assert len(b) < 256
    return bytes([len(b)]) + b


def login_value(entry_id, modified, title, user, pw, url, memo):
    v = struct.pack("<II", entry_id, modified)
    for field in (title, user, pw, url, memo):
        v += lp(field.encode())
    return v


def note_value(entry_id, modified, title, text):
    v = struct.pack("<II", entry_id, modified)
    v += lp(title.encode())
    comp = zlib.compress(text.encode(), 9)
    blob = bytes(c ^ DEVICE_ID[i % len(DEVICE_ID)] for i, c in enumerate(comp))
    return v + blob


NOTE = (
    "KEYVAULT secure note\n"
    "title: Cold wallet recovery\n"
    "updated: 2024-10-29\n"
    "\n"
    "If you are reading this, the app finally shut its doors for good.\n"
    "Support always swore these backups were unreadable off device.\n"
    "Support was an optimist.\n"
    "\n"
    "recovery pin: 4417\n"
    "seed words: harbor cedar violet anchor\n"
    "keepsake: " + FLAG + "\n"
)

records = []

# innocuous logins
records.append((0x01, login_value(
    1001, ts(2024, 3, 11, 18, 2), "GitHub", "m.okafor", "Gh!7xqP2_wink", "https://github.com", "work 2fa on")))
records.append((0x01, login_value(
    1002, ts(2024, 5, 27, 7, 41), "Gmail", "m.okafor@gmail.com", "pl0ver-staple-horse", "https://mail.google.com", "")))
records.append((0x01, login_value(
    1003, ts(2024, 8, 19, 22, 13), "Netflix", "okafor.home", "Bingewatch#2024", "https://netflix.com", "shared with fam")))
# the secret, buried in the middle
records.append((0x05, note_value(
    4096, ts(2024, 10, 29, 9, 13), "Cold wallet recovery", NOTE)))
records.append((0x01, login_value(
    1004, ts(2024, 2, 2, 11, 9), "HDFC NetBanking", "MO8841223", "Rupee$aver_90", "https://netbanking.hdfcbank.com", "")))
records.append((0x01, login_value(
    1005, ts(2024, 9, 30, 15, 55), "Spotify", "mokafor", "sixtracksdeep", "https://spotify.com", "")))
records.append((0x01, login_value(
    1006, ts(2024, 1, 20, 6, 30), "Router admin", "admin", "changeme-ofc", "http://192.168.0.1", "cafe guest ap")))


def build():
    header = b"KVLT"
    header += bytes([0x02])            # version
    header += bytes([0x01])            # flags
    header += struct.pack("<H", len(records))
    header += struct.pack("<I", CREATED)
    header += DEVICE_ID
    header += struct.pack("<H", APP_BUILD)
    header += b"\x00\x00"
    assert len(header) == 32, len(header)

    body = b""
    for rtype, value in records:
        body += bytes([rtype]) + struct.pack("<H", len(value)) + value

    blob = header + body
    blob += struct.pack("<I", binascii.crc32(blob) & 0xffffffff)
    return blob


if __name__ == "__main__":
    data = build()
    with open(OUT, "wb") as f:
        f.write(data)
    # handout zip holds only the container file
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(OUT, arcname=OUT)
    print("wrote", OUT, len(data), "bytes")
    print("wrote", ZIP)
    print("records", len(records))
    print("crc32", hex(binascii.crc32(data[:-4]) & 0xffffffff))
