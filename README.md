# edifier-ble

Unofficial scripts for controlling the volume of an **Edifier MR3** speaker over Bluetooth Low Energy (BLE), with an optional bridge to MQTT and Home Assistant.

> **Only tested on the Edifier MR3.** Other speakers that work with Edifier's ConneX app may use the same protocol, but that is unverified. Not affiliated with or endorsed by Edifier. Use at your own risk.

## What works

| Feature | Status |
|---|---|
| Read / set volume (0-30) | Working |
| MQTT bridge with Home Assistant auto-discovery | Working |
| EQ / mode switching | Works on the MR3, but not in these scripts yet |
| Configuring EQ settings | Not possible from here yet |
| Power off | Not working yet |

## Requirements

- Python 3.11 or newer
- A Bluetooth adapter with BlueZ (tested on a Raspberry Pi 5 running Python 3.13)
- For the bridge: an MQTT broker such as Mosquitto, and Home Assistant with the MQTT integration

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install bleak aiomqtt
```

On Raspberry Pi OS you can skip the venv and run `pip install bleak aiomqtt --break-system-packages`. If you only want the command-line volume control, `bleak` is enough.

## 1. Find your speaker's address

Turn the speaker on and close the ConneX app, then run:

```bash
python3 mr3_ble_explore.py scan
```

Look for **EDIFIER BLE** in the list. The value at the start of that line (like `AA:BB:CC:DD:EE:FF`) is the address you'll use below.

## 2. Set the volume from the command line

```bash
python3 mr3_volume.py AA:BB:CC:DD:EE:FF get
python3 mr3_volume.py AA:BB:CC:DD:EE:FF set 15
```

Volume is 0 to 30. Each command opens a new Bluetooth connection, so expect a delay of a second or two.

## 3. Run the MQTT bridge

The bridge keeps one connection open, so volume changes are instant. It reads its settings from environment variables. Nothing loads a `.env` file automatically, so load it yourself:

```bash
cp .env.example .env         # then edit .env
set -a; . ./.env; set +a     # load it into this shell
python3 mr3_mqtt_bridge.py
```

In `.env`, set at least `MR3_BLE_ADDRESS`. Set `MQTT_HOST` if your broker isn't on the same machine, and `MQTT_USERNAME` / `MQTT_PASSWORD` if it needs a login. `.env` is git-ignored; never commit it.

You should see `BLE connected`, then `Speaker reports volume=...`. In Home Assistant, a device called **Edifier MR3** with a volume slider appears on its own. The slider also follows the speaker's knob.

| MQTT topic | Purpose |
|---|---|
| `edifier_mr3/volume/set` | Publish a number 0-30 to set the volume |
| `edifier_mr3/volume/state` | Current volume |
| `edifier_mr3/availability` | `online` / `offline` |

### Run it on boot (systemd)

Create `/etc/systemd/system/mr3-bridge.service`, replacing the paths and user:

```ini
[Unit]
Description=Edifier MR3 BLE-MQTT bridge
After=bluetooth.target network-online.target
Wants=network-online.target
# Only needed if the repo is on a separate drive:
# RequiresMountsFor=/path/to/mount

[Service]
ExecStart=/usr/bin/python3 /path/to/edifier-ble/mr3_mqtt_bridge.py
EnvironmentFile=/path/to/edifier-ble/.env
Restart=always
RestartSec=5
User=YOUR_USER

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mr3-bridge
journalctl -u mr3-bridge -f
```

If you installed the dependencies in a virtual environment, point `ExecStart` at that environment's `python3` instead of `/usr/bin/python3`.

## Other scripts

- `mr3_ble_explore.py dump <address>` lists the speaker's Bluetooth services and characteristics. `write <address> <uuid> <hex>` sends raw bytes to a characteristic. Both are for exploring; unknown commands may change speaker settings.
- `parse_btsnoop_att.py btsnoop.log` turns an Android Bluetooth HCI snoop log into plain-text ATT reads, writes and notifications, which is how the protocol was found. On Android, turn on **Enable Bluetooth HCI snoop log** in Developer options, use the ConneX app, then copy the log off the phone.

## Troubleshooting

**"Device with address ... was not found"**: the speaker only accepts one BLE connection at a time, and it stops advertising while something else holds it. Close the ConneX app, stop any other copy of the bridge, and turn off other phones' Bluetooth. If that doesn't help, clear a stale connection with `bluetoothctl disconnect AA:BB:CC:DD:EE:FF`, or power-cycle the speaker.

**The ConneX app can't connect while the bridge is running**: same reason. Stop the bridge (`sudo systemctl stop mr3-bridge`) to use the app. Audio playback is not affected either way.

**`ModuleNotFoundError: bleak` or `aiomqtt`**: install the dependencies for the same Python that runs the script (see Requirements).

## Notes

- **Don't publish raw Bluetooth captures.** A btsnoop log includes every Bluetooth exchange your phone made while logging, including other devices' addresses. `.gitignore` excludes `*.log`, `*.cfa` and `att*.txt`.
- Never commit your `.env`. Only `.env.example` belongs in the repo.

## Protocol

The frame format is: `<AA or BB> EC <command> 00 <length> <payload...> <checksum>`, where the checksum is the sum of all preceding bytes modulo 256. Set volume is command `67`, get volume is `66`. A full write-up isn't included yet.

## License

MIT. See [LICENSE](LICENSE).
