# dbus-epever-tracer

**A Venus OS driver for EPEVER Tracer MPPT Solar Charge Controllers**

Bridges an EPEVER Tracer controller to Victron's Venus OS ecosystem over Modbus RTU (RS-485), exposing real-time and historical data on DBus so the Venus OS device and all Victron tools can see the charger exactly like a native Victron MPPT.

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
Venus OS device (Cerbo GX, etc.)
     │  GX display / Modbus-TCP gateway / Node-RED / …
     │
VRM portal (remote monitoring, via internet)
```

The driver is a Python 3 process that:

1. Opens the RS-485 serial port at startup (port passed as a CLI argument by `serial-starter`).
2. Syncs the controller's real-time clock to system time if drift exceeds 60 seconds.
3. Reads six blocks of Modbus registers once per second.
4. Converts raw register values to SI units and maps EPEVER states/errors to Victron equivalents.
5. Publishes everything across three DBus services, which the Venus OS device picks up automatically.

The three DBus services registered:

| Service | Type | Purpose |
|---|---|---|
| `com.victronenergy.solarcharger.ttyUSBx` | Solar charger | Main charger data, history, alarms |
| `com.victronenergy.temperature.ttyUSBx` | Temperature | Controller internal temperature sensor |
| `com.victronenergy.switch.ttyUSBx` | DC switch | Controllable load output |

---

## Features

- Real-time PV voltage, current, and power
- Battery voltage, current, and temperature
- Controller internal temperature on a dedicated `com.victronenergy.temperature` DBus service
- Load current, on/off state, and fault detection
- **Controllable load output** — exposed as a `com.victronenergy.switch` service; toggle from the GX display or VRM
- Victron charging state (Bulk / Absorption / Float / Equalise)
- **Absorption detection** — EPEVER combines Bulk and Absorption into one phase; the driver splits them using the absorption voltage setpoint (0x9007) and boost duration (0x906C)
- Daily and historical yield (kWh)
- Daily max/min voltages, max power, max battery current
- Time spent in each charging phase per day
- Up to 30 days of rolling history
- EPEVER fault bits translated to Victron MPPT error codes
- EPEVER status bits translated to Victron warning codes
- **High-temperature alarm** (`/Alarms/HighTemperature`) from controller discrete input 0x2000
- **State persistence** — daily accumulators and 30-day history saved to `/data/dbus-epever-tracer/state.json` every tick; restored on restart so a driver restart within the same day loses no data
- **Automatic controller clock sync** — on startup the driver compares the controller RTC to system time and writes the correct time if drift exceeds 60 seconds
- **Custom device names** — all three services expose a writeable `/CustomName` DBus path; names are saved to `state.json` and restored across restarts
- Automatic reconnection: exits after 3 consecutive Modbus failures so the supervisor restarts it

---

## DBus paths published

### Solar charger service (`com.victronenergy.solarcharger.ttyUSBx`)

| Path | Unit | Description |
|---|---|---|
| `/CustomName` | — | User-defined device name (writeable) |
| `/Dc/0/Voltage` | V | Battery voltage |
| `/Dc/0/Current` | A | Battery charging current |
| `/Pv/V` | V | PV array voltage |
| `/Yield/Power` | W | Instantaneous PV power |
| `/Yield/User` | kWh | Total generated energy (lifetime) |
| `/Yield/System` | kWh | Same as User |
| `/Load/I` | A | Load output current |
| `/Load/State` | — | Load output on/off |
| `/State` | — | Victron charging state (0/3/4/5/6) |
| `/ErrorCode` | — | Victron MPPT error code |
| `/WarningCode` | — | Victron warning code |
| `/Alarms/HighTemperature` | — | `0` = Normal, `2` = Alarm (from register 0x2000) |
| `/History/Daily/0/*` | — | Today's statistics (live) |
| `/History/Daily/1/*` … `/History/Daily/30/*` | — | Previous 30 days |
| `/History/Overall/*` | — | Lifetime max/min |

Victron charging state values: `0` = Off, `3` = Bulk, `4` = Absorption, `5` = Float, `6` = Storage/Equalise.

### Temperature service (`com.victronenergy.temperature.ttyUSBx`)

| Path | Unit | Description |
|---|---|---|
| `/CustomName` | — | User-defined device name (writeable) |
| `/Temperature` | °C | Controller internal temperature (register 0x3111) |
| `/TemperatureType` | — | `0` = Battery sensor type |

### Switch service (`com.victronenergy.switch.ttyUSBx`)

| Path | Description |
|---|---|
| `/CustomName` | User-defined device name (writeable) |
| `/SwitchableOutput/output_1/State` | Current load output state (writeable) |
| `/SwitchableOutput/output_1/Settings/CustomName` | User-defined output label (writeable) |
| `/SwitchableOutput/output_1/Status` | `9` = Normal, `13` = Fault |
| `/SwitchableOutput/output_1/Current` | Load output current |
| `/ModuleVoltage` | Battery voltage (mirror) |

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
wget -O setup-epever-driver.sh https://github.com/peterxxl/dbus-epever-tracer/raw/master/setup-epever-driver.sh && chmod +x setup-epever-driver.sh && ./setup-epever-driver.sh
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
6. Prompt for a custom device name, serial number, and VRM instance number (all optional — sensible defaults are used if skipped).
7. Restart `serial-starter` so the driver starts immediately — no reboot needed.

**Update** downloads the latest release and restarts the driver in place. Device name, serial number, and VRM instance are not changed during an update — edit them directly in `/data/dbus-epever-tracer/state.json` or via the DBus `/CustomName` path if needed.

**Remove** cleanly undoes every change the installer made:
- Stops and removes the driver service
- Removes symlinks from `/opt/victronenergy/`
- Removes only the epever line from `serial-starter.conf`
- Removes only the Epever udev rule from the rules file
- Removes boot hook entries from `/data/rcS.local` and `/data/rc.local`
- Optionally deletes the driver files from `/data/dbus-epever-tracer/`

---

## Configuration

Device-specific settings are stored in `/data/dbus-epever-tracer/state.json` and set during installation. They can be changed at any time by editing the file directly (restart the driver afterwards) or, for names, by writing to the `/CustomName` DBus path from any Victron tool.

| Key | Default | Description |
|---|---|---|
| `customname_charger` | `PV Charger` | Name shown for the solar charger service |
| `customname_temp` | `PV Charger Temperature` | Name shown for the temperature service |
| `customname_switch` | `PV Charger Load Output` | Name shown for the switch service |
| `serialnumber` | _(empty)_ | Serial number shown on the Venus OS device and VRM portal |
| `deviceinstance` | `278` | VRM instance number — must be unique per product type on the same Venus OS installation |

---

## Troubleshooting

**No data on the Venus OS device or VRM portal**
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

## Tools

All three tools require the driver to be stopped first — they cannot share the serial port with the running driver:

```sh
svc -d /service/dbus-epever-tracer.ttyUSB0   # stop
# run tool
svc -u /service/dbus-epever-tracer.ttyUSB0   # resume
```

---

## Live Monitor

`tools/epever-monitor.py` reads every available Modbus register block and displays them in a colour-coded terminal UI. Use it to verify readings, debug communication issues, or capture raw Modbus frames for analysis.

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

The display shows: PV voltage / current / power, battery voltage / current / charging power, load current and state, charging state, battery SOC and temperature, controller temperature, today's and yesterday's statistics (generated energy, max/min voltages, max power), lifetime totals, charging parameters, and the controller's real-time clock with drift from system time.

---

## Controller Configuration

`tools/epever-config.py` lets you read and change all writable controller parameters interactively. It displays current values alongside allowed ranges or options, and reads the register back after each write to confirm the controller accepted the change.

```sh
python3 /data/dbus-epever-tracer/tools/epever-config.py [port] [slave_addr]
```

Parameters covered:

- Battery type, capacity, rated voltage, and management mode
- All charging voltage thresholds (HVD, charging limit, equalization, boost, float, reconnect, LVD, etc.)
- Temperature compensation and temperature protection limits
- Boost and equalization duration and cycle
- Sun detection thresholds (NTTV / DTTV) and delays
- Load control mode and default load state

Example session:

```
  EPEVER Tracer Configuration  port /dev/ttyUSB0  slave 1

    #  Addr      Parameter                      Current value      Allowed range / options
    ──────────────────────────────────────────────────────────────────────────────────────
    1.  0x9000   Battery type                   Sealed             0=User defined  |  1=Sealed  |  2=GEL  |  3=Flooded
    2.  0x9001   Battery capacity               200 Ah             1 – 9999 Ah
    9.  0x9007   Boost / absorption voltage     28.80 V            9.0 – 32.0 V
   ...

  Enter parameter number to edit, r to refresh, or q to quit:
```

After entering a new value and confirming, the tool writes it to the controller and reports whether the value was accepted:

```
  Writing… OK  controller confirmed 29.00 V
```

---

## Clock Sync

`tools/epever-update-clock.py` reads the controller's internal real-time clock, compares it to the system clock, and optionally sets it to the correct local time.

The driver also syncs the clock automatically on startup if drift exceeds 60 seconds, so manual use of this tool is rarely needed.

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
│   ├── epever-config.py             Interactive controller configuration tool
│   ├── epever-update-clock.py       Sync controller RTC to system clock
│   └── epever_rtc.py                Shared RTC register helpers (used by driver and tools)
├── epsolar_modbus_protocol_map.md   EPEVER register reference
├── setup-epever-driver.sh           Install / update / remove
├── setup-post-os-update.sh                         Post-update OS config (boot hooks, symlinks, udev)
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
