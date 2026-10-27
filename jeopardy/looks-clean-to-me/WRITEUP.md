# Looks Clean to Me (forensics, medium) staff TLDR

Open the pcap. Among normal browsing noise the workstation makes a long run of DNS A queries to one zone, `cdn-sync.xyz`, each name shaped `<seq>.<base32>.cdn-sync.xyz` (base32 alphabet A to Z and 2 to 7). Ignore the same zone decoys (`www/api/status.cdn-sync.xyz`) and the red herring telemetry/cache zones, which do not fit that pattern.

Pull the matching queries, sort by the numeric `seq` label (they are sent out of order), concatenate the base32 labels, pad back to a multiple of 8, and base32 decode. The bytes start with `PK`, so it is a ZIP; inside is `harvested/notes.txt` with the flag. `solve.py` does all of this from the pcap alone.

Carrier traffic is only there to blend in: TLS browsing to real services and benign DNS lookups. The exfil responses and the same zone decoys resolve to `203.0.113.9`.
