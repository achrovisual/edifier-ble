#!/usr/bin/env python3
"""
Parse an Android btsnoop log and print out BLE GATT (ATT protocol)
traffic as plain text lines -- no Wireshark needed.

Usage:
    python3 parse_btsnoop_att.py btsnoop.log
    python3 parse_btsnoop_att.py btsnoop.log > att_writes.txt

Each line printed looks like:
    [12.345s] WRITE_REQUEST  handle=0x002a  value=64 00
    [12.401s] WRITE_RESPONSE handle=0x002a
    [12.500s] NOTIFICATION   handle=0x002d  value=01 64

"handle" is the GATT attribute handle (not the same as a UUID, but you can
cross-reference it against a GATT dump, e.g. from the bleak explorer script,
to figure out which characteristic it belongs to).
"""
import struct
import sys

ATT_OPCODES = {
    0x0A: "READ_REQUEST",
    0x0B: "READ_RESPONSE",
    0x12: "WRITE_REQUEST",
    0x13: "WRITE_RESPONSE",
    0x52: "WRITE_COMMAND",
    0x1B: "NOTIFICATION",
    0x1D: "INDICATION_CONFIRM",
    0x1E: "INDICATION",
}

# opcodes that carry a handle + value payload right after the opcode byte
HANDLE_VALUE_OPCODES = {0x12, 0x52, 0x1B, 0x1E, 0x0A}


def parse(path):
    with open(path, "rb") as f:
        data = f.read()

    if data[:8] != b"btsnoop\x00":
        sys.stderr.write("Not a btsnoop file (missing magic header).\n")
        sys.exit(1)

    offset = 16  # global header
    count = 0
    first_ts = None

    while offset < len(data):
        if offset + 24 > len(data):
            break
        orig_len, incl_len, flags, drops, ts = struct.unpack_from(
            ">IIIIQ", data, offset
        )
        offset += 24
        packet = data[offset : offset + incl_len]
        offset += incl_len

        if len(packet) < 1:
            continue

        hci_type = packet[0]
        if first_ts is None:
            first_ts = ts
        elapsed = (ts - first_ts) / 1_000_000.0
        count += 1

        if hci_type != 0x02:  # only interested in ACL data (carries L2CAP/ATT)
            continue

        acl = packet[1:]
        if len(acl) < 4:
            continue
        handle_flags, data_len = struct.unpack_from("<HH", acl, 0)
        l2cap = acl[4 : 4 + data_len]
        if len(l2cap) < 4:
            continue
        l2cap_len, cid = struct.unpack_from("<HH", l2cap, 0)
        if cid != 0x0004:  # ATT fixed channel
            continue
        att = l2cap[4:]
        if len(att) < 1:
            continue

        opcode = att[0]
        name = ATT_OPCODES.get(opcode, f"OPCODE_0x{opcode:02x}")

        if opcode in HANDLE_VALUE_OPCODES and len(att) >= 3:
            att_handle = struct.unpack_from("<H", att, 1)[0]
            value = att[3:]
            hexval = " ".join(f"{b:02x}" for b in value)
            print(f"[{elapsed:8.3f}s] {name:<20} handle=0x{att_handle:04x}  value={hexval}")
        else:
            print(f"[{elapsed:8.3f}s] {name}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    parse(sys.argv[1])
