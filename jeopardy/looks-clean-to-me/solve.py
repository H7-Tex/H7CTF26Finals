#!/usr/bin/env python3
# dns exfil over cdn-sync.xyz: names are <seq>.<base32>.cdn-sync.xyz.
# order by seq, join the base32, decode -> zip -> flag.
import base64, io, re, sys, zipfile
from scapy.all import rdpcap, DNS, DNSQR

pcap = sys.argv[1] if len(sys.argv) > 1 else "capture.pcap"
pat = re.compile(r"^(\d+)\.([A-Z2-7]+)\.cdn-sync\.xyz\.?$")

chunks = {}
for p in rdpcap(pcap):
    if p.haslayer(DNS) and p[DNS].qr == 0 and p[DNS].qd:
        m = pat.match(p[DNSQR].qname.decode())
        if m:
            chunks.setdefault(int(m.group(1)), m.group(2))

b32 = "".join(chunks[i] for i in sorted(chunks))
raw = base64.b32decode(b32 + "=" * (-len(b32) % 8))

zf = zipfile.ZipFile(io.BytesIO(raw))
for name in zf.namelist():
    flag = re.search(rb"H7CTF\{[0-9a-f]{32}\}", zf.read(name))
    if flag:
        print(flag.group().decode())
