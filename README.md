# dbus-epever-tracer

**A Venus OS driver for EPEVER Tracer MPPT Solar Charge Controllers**

Bridges an EPEVER Tracer controller to Victron's Venus OS ecosystem over Modbus RTU (RS-485), exposing real-time and historical data on DBus so VRM and all other Victron tools can see the charger exactly like a native Victron MPPT.

---

## Tested hardware and software

| Component | Version / Model |
|---|---|
| Venus OS device | Victron Cerbo-S GX |
| Venus OS | v3.60, v3.72, v3.80 |
| Solar charge controller | EPEVER Tracer 3210A MPPT |
| RS-485 adapter | Victron Energy USB RS485 cable (FT232R chipset) |

Other Venus OS devices (Ekrano GX, Raspberry Pi with Venus OS, etc.) and other EPEVER Tracer models should work without changes.

---

## How it works

```
EPEVER Tracer
     │  Modbus RTU / RS-485
USB RS-485 adapter (/dev/ttyUSBx)
     │
dbus-epever-tracer.py   ← this driver
     │  DBus  com.victronenergy.solarcharger.ttyUSBx
Venus OS
     │
VRM / GX display / Modbus-TCP gateway / …
```

The driver is a Python 3 process that:

1. Opens the RS-485 serial port at startup (port passed as a CLI argument by `serial-starter`).
2. Reads four blocks of Modbus holding registers once per second.
3. Converts raw register values to SI units and maps EPEVER states/errors to Victron equivalents.
4. Publishes everything on a `com.victronenergy.solarcharger` DBus service, which Venus OS picks up automatically.

---

## Features

- Real-time PV voltage, current, and power
- Battery voltage, current, and temperature
- Load current and on/off state
- Victron charging state (Bulk / Absorption / Float / Equalise)
- Daily and historical yield (kWh)
- Daily max/min voltages, max power, max battery current
- Time spent in each charging phase per day
- EPEVER fault bits translated to Victron MPPT error codes
- Automatic reconnection: exits after 3 consecutive Modbus failures so the supervisor restarts it

---

## DBus paths published

| Path | Unit | Description |
|---|---|---|
| `/Dc/0/Voltage` | V | Battery voltage |
| `/Dc/0/Current` | A | Battery charging current |
| `/Dc/0/Temperature` | °C | Controller (internal) temperature |
| `/Pv/V` | V | PV array voltage |
| `/Yield/Power` | W | Instantaneous PV power |
| `/Yield/User` | kWh | Total generated energy (lifetime) |
| `/Yield/System` | kWh | Same as User |
| `/Load/I` | A | Load output current |
| `/Load/State` | — | Load output on/off |
| `/State` | — | Victron charging state (0/3/4/5/6) |
| `/ErrorCode` | — | Victron MPPT error code |
| `/History/Daily/0/*` | — | Today's statistics |
| `/History/Daily/1/*` | — | Yesterday's statistics |
| `/History/Overall/*` | — | Lifetime max/min |

Victron charging state values: `0` = Off, `3` = Bulk, `4` = Absorption, `5` = Float, `6` = Storage/Equalise.

---

## Hardware requirements

- A Venus OS device (Cerbo GX, Ekrano GX, Raspberry Pi with Venus OS, etc.)
- An EPEVER Tracer MPPT controller with an RS-485 port
- A USB–RS-485 adapter. The Victron Energy USB RS485 cable (FT232R chipset) is recommended because it is already handled by the included udev rule.

---

## Software requirements

- Venus OS v3.60 or later (tested up to v3.80)
- Root SSH access to the Venus OS device
- Internet access from the device during installation
- `minimalmodbus` Python library (bundled — no separate install needed)

---

## Installation, updating, and removal

A single script handles everything:

```sh
# SSH into your Venus OS device as root, then:
wget https://github.com/peterxxl/dbus-epever-tracer/raw/master/setup-epever-driver.sh
chmod +x setup-epever-driver.sh
./setup-epever-driver.sh
```

The script detects whether the driver is already installed and presents the appropriate options:

- **Not installed** — confirms and installs
- **Already installed** — offers to update or remove

**Install** will:

1. Download this repository and Victron's `velib_python` library.
2. Place files under `/data/dbus-epever-tracer/` (survives OS updates).
3. Add an `epever` entry to `/etc/venus/serial-starter.conf`.
4. Add a udev rule for the FT232R USB adapter.
5. Create symlinks under `/opt/victronenergy/` and register boot hooks.
6. Restart `serial-starter` so the driver starts immediately — no reboot needed.

**Update** downloads the latest release and restarts the driver in place.

**Remove** cleanly undoes every change the installer made:
- Stops and removes the driver service
- Removes symlinks from `/opt/victronenergy/`
- Removes only the epever line from `serial-starter.conf`
- Removes only the Epever udev rule from the rules file
- Removes boot hook entries from `/data/rcS.local` and `/data/rc.local`
- Optionally deletes the driver files from `/data/dbus-epever-tracer/`

---

## Customisation

Open `driver/dbus-epever-tracer.py` and edit the constants near the top of the file before installing (or after, then restart the service):

| Variable | Default | Purpose |
|---|---|---|
| `serialnumber` | `'WO20160415-008-0056'` | Device serial shown in VRM |
| `productname` | `'Epever Tracer MPPT'` | Product name shown in VRM |
| `firmwareversion` | _(auto-stamped)_ | Set to `vYYYY.MM.DD-HHMM` by the pre-commit hook on every commit |
| `deviceinstance` | `278` | VRM device instance number |

---

## Troubleshooting

**No data on VRM**
- Confirm the driver process is running: `ps aux | grep dbus-epever-tracer`
- Check that the serial adapter is visible: `ls /dev/ttyUSB*`
- Read the service log: `cat /var/log/dbus-epever-tracer.ttyUSB0/current`

**Driver fails to start**
- Check that the udev rule fired: `udevadm info /dev/ttyUSB0 | grep VE_SERVICE`

**Wrong serial port**
- The serial-starter daemon assigns the port automatically based on udev rules.  If you are using an adapter other than the FT232R, add a matching rule to `/etc/udev/rules.d/serial-starter.rules`.

**Restarting the driver manually**
```sh
svc -t /service/dbus-epever-tracer.ttyUSB0
```

---

## Live Monitor

`tools/epever-monitor.py` is a standalone diagnostic tool that reads every available Modbus register block and displays them in a colour-coded terminal UI. Use it to verify readings, debug communication issues, or capture raw Modbus frames for analysis.

**The driver and the monitor cannot share the serial port.** Stop the driver before running the monitor:

```sh
svc -d /service/dbus-epever-tracer.ttyUSB0
```

Run the monitor:

```sh
python3 /data/dbus-epever-tracer/tools/epever-monitor.py [port] [slave] [interval] [--dump]
```

| Argument | Default | Description |
|---|---|---|
| `port` | `/dev/ttyUSB0` | Serial device |
| `slave` | `1` | Modbus slave address |
| `interval` | `2.0` | Refresh interval in seconds |
| `--dump` | off | Capture one iteration of raw Modbus bytes to `epever-dump-TIMESTAMP.txt` alongside stdout, then exit |

Examples:

```sh
# Live display on the default port, 2-second refresh
python3 /data/dbus-epever-tracer/tools/epever-monitor.py

# Explicit port, slave address, and 5-second refresh
python3 /data/dbus-epever-tracer/tools/epever-monitor.py /dev/ttyUSB1 1 5

# Capture raw Modbus frames to a file for off-device analysis
python3 /data/dbus-epever-tracer/tools/epever-monitor.py /dev/ttyUSB0 1 2 --dump
```

The display shows: PV voltage / current / power, battery voltage / current / charging power, load current and state, charging state, battery SOC and temperature, controller temperature, today's and yesterday's statistics (generated energy, max/min voltages, max power), lifetime totals, charging parameters, and the controller's real-time clock.

Resume the driver when done:

```sh
svc -u /service/dbus-epever-tracer.ttyUSB0
```

---

## Clock Sync

`tools/epever-update-clock.py` reads the controller's internal real-time clock, compares it to the system clock, and optionally sets it to the correct local time. The EPEVER Tracer has no NTP — its clock drifts over time and needs occasional manual correction.

```sh
python3 /data/dbus-epever-tracer/tools/epever-update-clock.py [port] [slave_addr]
```

The tool shows the drift before writing and asks for confirmation:

```
  Controller : 2026-04-28 08:01:33
  System     : 2026-04-28 10:03:47   [+7334 s]

  Set controller clock to system time? [y/N]
```

Drift colour: green under 60 s, yellow under 300 s, red 300 s or more.

The tool reads the Venus OS timezone from DBus so the comparison uses true local time regardless of how the system timezone is configured.

**Stop the driver before running** (same requirement as the monitor):

```sh
svc -d /service/dbus-epever-tracer.ttyUSB0
python3 /data/dbus-epever-tracer/tools/epever-update-clock.py
svc -u /service/dbus-epever-tracer.ttyUSB0
```

---

## File structure

```
dbus-epever-tracer/
├── driver/
│   ├── dbus-epever-tracer.py        Main driver
│   └── start-dbus-epever-tracer.sh  Shell wrapper called by serial-starter
├── service/
│   ├── run                          Daemontools service run script
│   └── log/run                      Daemontools log run script
├── tools/
│   ├── epever-monitor.py            Live terminal monitor / raw dump tool
│   └── epever-update-clock.py       Sync controller RTC to system clock
├── epsolar_modbus_protocol_map.md   EPEVER register reference
├── setup-epever-driver.sh           Install / update / remove
├── setup.sh                         Post-update OS config (boot hooks, symlinks, udev)
└── serial-starter.rules.default     Example udev rules
```

After installation the live files live under `/data/dbus-epever-tracer/` with symlinks in `/opt/victronenergy/`.

---

## Contributing

Pull requests are welcome. Please keep changes focused — one logical change per PR. The driver is intentionally kept as a single Python file to make Venus OS deployment straightforward.

Useful references:
- [Victron DBus API](https://github.com/victronenergy/venus/wiki/dbus)
- [How to add a driver to serial-starter](https://github.com/victronenergy/venus/wiki/howto-add-a-driver-to-Venus#howto-add-a-driver-to-serial-starter)
- [EPEVER Tracer Modbus protocol](epsolar_modbus_protocol_map.md)

---

## Credits and licence

Based on original work by [kassl-2007](https://github.com/kassl-2007/dbus-epever-tracer) and improved by the community.

MIT licence — see [LICENSE.md](LICENSE.md).
