#!/usr/bin/env python3
"""
Edifier MR3 BLE explorer.

Run this on the Raspberry Pi (needs `pip install bleak --break-system-packages`).

Step 1: python3 mr3_ble_explore.py scan
    Finds the MR3's BLE advertisement and prints its address.

Step 2: python3 mr3_ble_explore.py dump AA:BB:CC:DD:EE:FF
    Connects and prints every GATT service/characteristic, with
    read/write/notify flags, so you know what's actually exposed.

Step 3 (optional, once you've captured the ConneX app's traffic and
know the characteristic UUID + byte pattern for volume):
    python3 mr3_ble_explore.py write AA:BB:CC:DD:EE:FF <char-uuid> <hex-bytes>
    e.g. write AA:BB:CC:DD:EE:FF 0000ff01-0000-1000-8000-00805f9b34fb 64
"""
import asyncio
import sys

from bleak import BleakClient, BleakScanner


async def scan():
    print("Scanning 10s for BLE devices (look for Edifier/MR3)...")
    devices = await BleakScanner.discover(timeout=10.0)
    for d in devices:
        name = d.name or "(no name)"
        print(f"{d.address}  {name}  rssi={getattr(d, 'rssi', '?')}")


async def dump(address):
    async with BleakClient(address) as client:
        print(f"Connected: {client.is_connected}")
        for service in client.services:
            print(f"\n[Service] {service.uuid}  {service.description}")
            for char in service.characteristics:
                props = ",".join(char.properties)
                print(f"  [Char] handle=0x{char.handle:04x} ({char.handle})  {char.uuid}  props=({props})")
                for desc in char.descriptors:
                    print(f"    [Desc] {desc.uuid}")


async def write(address, char_uuid, hex_bytes):
    data = bytes.fromhex(hex_bytes.replace(" ", ""))
    async with BleakClient(address) as client:
        await client.write_gatt_char(char_uuid, data, response=True)
        print(f"Wrote {data.hex()} to {char_uuid}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "scan":
        asyncio.run(scan())
    elif cmd == "dump":
        asyncio.run(dump(sys.argv[2]))
    elif cmd == "write":
        asyncio.run(write(sys.argv[2], sys.argv[3], sys.argv[4]))
    else:
        print(__doc__)
