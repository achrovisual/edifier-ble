#!/usr/bin/env python3
"""
Control the volume of an Edifier MR3 speaker over BLE, using the
proprietary command protocol reverse-engineered from a ConneX app
btsnoop capture.

Protocol:
    Every command is: AA EC <cmd> 00 <payload_len> [payload...] <checksum>
    checksum = sum(all preceding bytes) mod 256

    Set volume (write, no response), GATT handle 0x0009:
        AA EC 67 00 01 <level 0x00-0x1e> <checksum>

    Volume status notification, GATT handle 0x0006:
        BB EC 66 00 02 1E <level 0x00-0x1e> <checksum>
        (MR3-specific: 0x1E / 30 is the maximum volume; may differ on other models)

Usage:
    python3 mr3_volume.py <mac_address> set <0-30>
    python3 mr3_volume.py <mac_address> get
"""
import asyncio
import sys

from bleak import BleakClient

# MR3-specific: control-service UUIDs observed on the Edifier MR3. Unverified on other models.
VOLUME_HANDLE_WRITE = "48090002-1a48-11e9-ab14-d663bd873d93"
VOLUME_HANDLE_NOTIFY = "48090001-1a48-11e9-ab14-d663bd873d93"

CMD_SET_VOLUME = 0x67
CMD_GET_VOLUME = 0x66


def checksum(payload_bytes):
    return sum(payload_bytes) % 256


def build_packet(cmd, data=b""):
    body = bytes([0xAA, 0xEC, cmd, 0x00, len(data)]) + data
    return body + bytes([checksum(body)])


async def set_volume(address, level):
    # MR3-specific: volume range is 0-30. Other models may differ.
    if not 0 <= level <= 30:
        raise ValueError("Volume level must be 0-30")
    packet = build_packet(CMD_SET_VOLUME, bytes([level]))
    async with BleakClient(address) as client:
        await client.write_gatt_char(VOLUME_HANDLE_WRITE, packet, response=False)
        print(f"Sent volume={level} ({packet.hex()})")


async def get_volume(address):
    result = {}
    event = asyncio.Event()

    def handle_notify(_, data: bytearray):
        # Expect (on the 48090001... notify characteristic):
        # bb ec 66 00 02 1e <level> <checksum>
        # MR3-specific: 0x1e (30) is the maximum volume, so it may differ on other models.
        if len(data) >= 7 and data[0] == 0xBB and data[2] == CMD_GET_VOLUME:
            result["level"] = data[6]
            event.set()

    async with BleakClient(address) as client:
        await client.start_notify(VOLUME_HANDLE_NOTIFY, handle_notify)
        packet = build_packet(CMD_GET_VOLUME)
        await client.write_gatt_char(VOLUME_HANDLE_WRITE, packet, response=False)
        try:
            await asyncio.wait_for(event.wait(), timeout=5.0)
            # MR3-specific: volume range is 0-30. Other models may differ.
            print(f"Current volume: {result['level']} / 30")
        except asyncio.TimeoutError:
            print("No response received (timed out waiting for notification)")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    address = sys.argv[1]
    action = sys.argv[2]

    if action == "set":
        level = int(sys.argv[3])
        asyncio.run(set_volume(address, level))
    elif action == "get":
        asyncio.run(get_volume(address))
    else:
        print(__doc__)
        sys.exit(1)
