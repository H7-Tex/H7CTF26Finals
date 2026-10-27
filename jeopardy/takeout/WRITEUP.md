# Takeout - staff TLDR

Intended solve (no format spec is given to players):

1. `takeout.zip` holds one `.kvlt` file in an undocumented container: 32-byte header (magic `KVLT`, version, record count, timestamp, a 16-byte `device_id`), then a flat table of type/length/value records, then a trailing CRC32 over the whole file.
2. Walk the TLV records. Most are login entries with readable length-prefixed fields; exactly one record (type `0x05`) carries a plaintext title then a blob of high-entropy bytes. That blob is the target. The CRC confirms the field widths were parsed correctly.
3. The only key-sized thing in the file is `device_id`. XOR the blob against it (repeating) and a zlib stream (`0x78 ...`) appears; inflate it to get the secure note. The flag is the note's `keepsake:` line.

Obfuscation is keyed entirely off in-file data, so no external or guessed key is needed. `solve.py <takeout.zip>` automates all of it.
