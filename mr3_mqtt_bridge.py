#!/usr/bin/env python3
"""
Persistent bridge between the Edifier MR3 (BLE) and MQTT / Home Assistant.

Keeps a single long-lived BLE connection open (instead of reconnecting per
command like the earlier scripts), and:
  - Subscribes to a "set volume" MQTT topic, forwards commands to the speaker
  - Publishes the speaker's current volume to a "state" MQTT topic, both on
    startup and whenever the speaker reports a change (e.g. someone turns
    the physical knob or uses the ConneX app -- HA will stay in sync)
  - Publishes Home Assistant MQTT discovery config, so a "number" entity
    for volume shows up in HA automatically, no YAML needed

Install deps:
    pip install bleak aiomqtt --break-system-packages

Set the environment variables described in the CONFIG section below, then run:
    MR3_BLE_ADDRESS=AA:BB:CC:DD:EE:FF python3 mr3_mqtt_bridge.py

For always-on use, run this as a systemd service (see comment at bottom).
"""
import asyncio
import logging
import os

from bleak import BleakClient
import aiomqtt

# ---------------------------------------------------------------------------
# CONFIG -- set via environment variables (never hardcode your own details here)
#
#   MR3_BLE_ADDRESS   speaker's BLE address, e.g. from `mr3_ble_explore.py scan`
#   MQTT_HOST         default: localhost
#   MQTT_PORT         default: 1883
#   MQTT_USERNAME     optional
#   MQTT_PASSWORD     optional
# ---------------------------------------------------------------------------
BLE_ADDRESS = os.environ.get("MR3_BLE_ADDRESS", "AA:BB:CC:DD:EE:FF")

MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USERNAME = os.environ.get("MQTT_USERNAME") or None
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD") or None

# ---------------------------------------------------------------------------
CHAR_WRITE = "48090002-1a48-11e9-ab14-d663bd873d93"
CHAR_NOTIFY = "48090001-1a48-11e9-ab14-d663bd873d93"

CMD_SET_VOLUME = 0x67
CMD_GET_VOLUME = 0x66

TOPIC_SET = "edifier_mr3/volume/set"
TOPIC_STATE = "edifier_mr3/volume/state"
TOPIC_AVAILABILITY = "edifier_mr3/availability"
DISCOVERY_TOPIC = "homeassistant/number/edifier_mr3_volume/config"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("mr3-bridge")


def checksum(b):
    return sum(b) % 256


def build_packet(cmd, data=b""):
    body = bytes([0xAA, 0xEC, cmd, 0x00, len(data)]) + data
    return body + bytes([checksum(body)])


class MR3Bridge:
    def __init__(self):
        self.ble_client: BleakClient | None = None
        self.mqtt_client: aiomqtt.Client | None = None

    async def ble_notify_handler(self, _, data: bytearray):
        if len(data) >= 7 and data[0] == 0xBB and data[2] == CMD_GET_VOLUME:
            level = data[6]
            log.info(f"Speaker reports volume={level}")
            if self.mqtt_client:
                await self.mqtt_client.publish(TOPIC_STATE, str(level), retain=True)

    async def ensure_ble_connected(self):
        if self.ble_client and self.ble_client.is_connected:
            return
        log.info(f"Connecting to {BLE_ADDRESS}...")
        self.ble_client = BleakClient(BLE_ADDRESS)
        await self.ble_client.connect()
        await self.ble_client.start_notify(CHAR_NOTIFY, self.ble_notify_handler)
        log.info("BLE connected")
        # ask the speaker for its current volume so HA starts in sync
        packet = build_packet(CMD_GET_VOLUME)
        await self.ble_client.write_gatt_char(CHAR_WRITE, packet, response=False)

    async def set_volume(self, level: int):
        level = max(0, min(30, level))
        await self.ensure_ble_connected()
        packet = build_packet(CMD_SET_VOLUME, bytes([level]))
        await self.ble_client.write_gatt_char(CHAR_WRITE, packet, response=False)
        log.info(f"Sent volume={level}")

    async def ble_keepalive_loop(self):
        while True:
            try:
                await self.ensure_ble_connected()
            except Exception as e:
                log.warning(f"BLE connect failed: {e}, retrying in 10s")
            await asyncio.sleep(10)

    async def mqtt_loop(self):
        while True:
            try:
                async with aiomqtt.Client(
                    hostname=MQTT_HOST,
                    port=MQTT_PORT,
                    username=MQTT_USERNAME,
                    password=MQTT_PASSWORD,
                    will=aiomqtt.Will(TOPIC_AVAILABILITY, "offline", retain=True),
                ) as client:
                    self.mqtt_client = client
                    await client.publish(TOPIC_AVAILABILITY, "online", retain=True)
                    await self.publish_discovery(client)
                    await client.subscribe(TOPIC_SET)
                    log.info("MQTT connected, subscribed to %s", TOPIC_SET)

                    async for message in client.messages:
                        if message.topic.matches(TOPIC_SET):
                            try:
                                level = int(float(message.payload.decode()))
                                await self.set_volume(level)
                            except Exception as e:
                                log.error(f"Bad volume payload: {message.payload!r} ({e})")
            except Exception as e:
                log.warning(f"MQTT connection error: {e}, retrying in 5s")
                await asyncio.sleep(5)

    async def publish_discovery(self, client):
        config = {
            "name": "Edifier MR3 Volume",
            "unique_id": "edifier_mr3_volume",
            "command_topic": TOPIC_SET,
            "state_topic": TOPIC_STATE,
            "availability_topic": TOPIC_AVAILABILITY,
            "min": 0,
            "max": 30,
            "step": 1,
            "mode": "slider",
            "device": {
                "identifiers": ["edifier_mr3"],
                "name": "Edifier MR3",
                "manufacturer": "Edifier",
                "model": "MR3",
            },
        }
        import json
        await client.publish(DISCOVERY_TOPIC, json.dumps(config), retain=True)
        log.info("Published HA discovery config")

    async def run(self):
        await asyncio.gather(
            self.ble_keepalive_loop(),
            self.mqtt_loop(),
        )


if __name__ == "__main__":
    asyncio.run(MR3Bridge().run())

"""
--- Running as a systemd service (recommended for always-on use) ---

Create /etc/systemd/system/mr3-bridge.service:

    [Unit]
    Description=Edifier MR3 BLE-MQTT bridge
    After=bluetooth.target network-online.target
    Wants=network-online.target

    [Service]
    ExecStart=/usr/bin/python3 /path/to/mr3_mqtt_bridge.py
    EnvironmentFile=/etc/mr3-bridge.env
    Restart=always
    RestartSec=5
    User=YOUR_USER

    [Install]
    WantedBy=multi-user.target

Put your settings in /etc/mr3-bridge.env (keep it out of git, chmod 600):

    MR3_BLE_ADDRESS=AA:BB:CC:DD:EE:FF
    MQTT_HOST=localhost
    MQTT_USERNAME=
    MQTT_PASSWORD=

Then:
    sudo systemctl daemon-reload
    sudo systemctl enable --now mr3-bridge
    sudo systemctl status mr3-bridge      # check it's running
    journalctl -u mr3-bridge -f           # follow logs
"""
