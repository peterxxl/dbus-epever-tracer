# AGENTS.md — guidance for AI coding agents

This file tells AI coding assistants (Claude Code, GitHub Copilot, etc.) the things they need to know about this repository that are not obvious from reading the code.

---

## What this project is

A single-file Python 3 driver that runs on a Victron Venus OS device and makes an EPEVER Tracer MPPT solar charge controller visible to the Victron ecosystem (VRM, GX display, Modbus-TCP gateway, etc.).

The driver sits between two protocols:

- **Modbus RTU over RS-485** (towards the EPEVER controller)
- **DBus** (towards Venus OS)

Everything important is in `driver/dbus-epever-tracer.py`.

---

## Architecture in one diagram

```
EPEVER Tracer hardware
     │ RS-485 serial (Modbus RTU, 115 200 baud, slave addr 1)
/dev/ttyUSBx
     │ minimalmodbus.Instrument
dbus-epever-tracer.py  ← single Python process
     │ dbus-python + GLib main loop
com.victronenergy.solarcharger.ttyUSBx  (system DBus service)
     │
Venus OS (VRM, GX display, Node-RED, …)
```

The process is supervised by daemontools/runit (Venus OS standard). If it exits, it is restarted automatically. The driver deliberately exits after 3 consecutive Modbus failures to trigger this restart.

---

## Key files

| File | Role |
|---|---|
| `driver/dbus-epever-tracer.py` | Entire driver logic — Modbus reads, value conversion, DBus publishing |
| `driver/start-dbus-epever-tracer.sh` | Shell wrapper; sources Victron's `run-service.sh` then calls the Python script with the serial port |
| `service/run` | Daemontools run script; redirects stderr and launches the shell wrapper |
| `service/log/run` | Daemontools log script; runs `multilog` to rotate logs |
| `setup-epever-driver.sh` | Combined installer / updater / remover for Venus OS |
| `setup.sh` | Idempotent post-update OS config (symlinks, serial-starter, udev, boot hooks) |
| `epsolar_modbus_protocol_map.md` | Full EPEVER LS-B register map plus Tracer 3210A compatibility notes |
| `serial-starter.rules.default` | Example udev rules; the installer appends a rule to the live file |
| `tools/epever-monitor.py` | Standalone live terminal monitor — reads all register blocks, colour-coded display, `--dump` mode for raw frame capture |
| `tools/epever-update-clock.py` | Reads the controller RTC, shows drift vs system clock, optionally writes system time to controller |

The Victron `velib_python` library is **not** in this repo. The installer downloads it at runtime and places it at `ext/velib_python/` relative to the driver directory. The driver adds that path to `sys.path` before importing `vedbus`.

`minimalmodbus` is **bundled** in `ext/` inside this repo. It does not need to be installed via pip.

---

## Modbus register blocks read every second

| Variable | Start address | Count | FC | Content |
|---|---|---|---|---|
| `c3100` | `0x3100` | 18 | 4 | PV voltage/current/power, battery voltage/current/temp, load data |
| `c3200` | `0x3200` | 3 | 4 | Battery status flags, charging status flags, load on/off |
| `c3300` | `0x3300` | 20 | 4 | Daily max/min voltages and energy, total generated energy |
| `c330C` | `0x330C` | 2 | 4 | Today's generated energy (kWh × 100) — read separately |
| `boostchargingvoltage` | `0x9002` | 2 | 3 | Boost and float voltage setpoints (V × 100) |

**Tracer 3210A register limits** — requesting more registers than listed above returns Modbus exception 02 and corrupts the serial buffer for subsequent reads. See `epsolar_modbus_protocol_map.md` for full compatibility notes.

All voltage, current, and power values are stored as integers scaled by 100 (e.g. 2450 = 24.50 V). Divide by 100 to get SI units.

32-bit power values use two consecutive registers: `low | (high << 16)`.

Registers `0x311A`, `0x311B`, and `0x311D` (SOC, remote battery temp, system rated voltage) must be read **one at a time** — reading them as a block causes cascade failures on the Tracer 3210A.

---

## Serial port startup flush

On startup the driver calls `controller.serial.reset_input_buffer()` twice with a 100 ms sleep between them. This drains any bytes left in the FT232R USB FIFO from a previous session, which would otherwise arrive during the first read and cause a checksum error.

---

## Charging state mapping

EPEVER encodes the charging phase in bits 3–2 of register `0x3201`:

| Bits [3,2] | EPEVER meaning | Victron state |
|---|---|---|
| 00 | Not charging | 0 (Off) |
| 01 | Float | 5 (Float) |
| 10 | Boost / Bulk | 3 (Bulk) |
| 11 | Equalising | 6 (Storage) |

The driver also promotes state 3 → 4 (Absorption) when in Bulk but the battery voltage already exceeds the float setpoint (`boostchargingvoltage[1] / 100`).

---

## Error mapping

`map_epever_error(batt_status, chg_status)` converts EPEVER status bits to a Victron MPPT error code. Only a subset of Victron codes is used because EPEVER exposes fewer fault conditions. The mapping is defined in `ERROR_MAP` at module level.

---

## Daily statistics and midnight rollover

**Voltage max/min** (`MaxPvVoltage`, `MinBatteryVoltage`, `MaxBatteryVoltage`) are read directly from controller registers `0x3300–0x3303` on every update tick. The controller maintains and resets these at midnight — the driver does not track or reset them.

**Max power and max battery current** have no controller register and are tracked in driver memory, reset at midnight.

**Time-in-phase** (`_time_in_bulk`, `_time_in_absorption`, `_time_in_float`) is accumulated in floating-point minutes and rounded to whole minutes before being written to DBus.

**State persistence** — the driver saves daily accumulators (time-in-phase, max power, max battery current, yesterday's values) to a JSON file at `/data/dbus-epever-tracer/state.json` on every update tick. On startup it restores these values if the file's date matches today. This means a driver restart no longer loses the current day's accumulated time-in-phase or max power.

**Overall lifetime max/min** — tracked in driver memory by comparing against the daily register values each tick. Not persisted across restarts.

---

## DBus service name and device instance

The service name is `com.victronenergy.solarcharger.<port>` where `<port>` is the last component of the serial device path (e.g. `ttyUSB0`). This means multiple instances can run concurrently on different ports.

The device instance (`deviceinstance = 278`) is the number shown in VRM. Change it if another device on the same system already uses 278.

---

## Dependencies

| Dependency | Source | Notes |
|---|---|---|
| `minimalmodbus` | Bundled in `ext/` | Modbus RTU client — no install needed |
| `dbus-python` | Venus OS system package | DBus bindings |
| `PyGObject` (GLib) | Venus OS system package | Main event loop |
| `pyserial` | Bundled with minimalmodbus | Serial port I/O |
| `velib_python` (vedbus) | Downloaded by installer from GitHub | Victron DBus helper |

Do not add new runtime dependencies without updating the installer and this file.

---

## Tools

Both tools in `tools/` require the driver to be stopped first — they cannot share the serial port with the running driver.

```sh
svc -d /service/dbus-epever-tracer.ttyUSB0   # stop
# run tool
svc -u /service/dbus-epever-tracer.ttyUSB0   # resume
```

Both tools read the Venus OS timezone from `com.victronenergy.settings /Settings/System/TimeZone` via DBus so that local time is correct even when the `TZ` environment variable is not set.

---

## Testing and validation

There is no automated test suite. The only way to validate a change is to run it on real hardware (Venus OS + EPEVER controller). When working without hardware:

- Use `minimalmodbus`'s debug mode or a Modbus simulator to supply synthetic register data.
- Read the log output from `/var/log/dbus-epever-tracer.ttyUSBx/current` on the device.
- Use `dbus-spy` or `dbus-monitor` on the Venus OS device to inspect live DBus values.

---

## Things to watch out for

- **Python version:** Venus OS ships Python 3. The shebang is `#!/usr/bin/env python3`. Do not use Python 2 syntax.
- **Single-file constraint:** The driver is intentionally one file. Do not split it into a package without updating the installer and the start script.
- **Serial port from CLI:** The serial port path is `sys.argv[1]`. The Modbus instrument and the DBus service name are both derived from it at startup.
- **Exception counter:** Module-level integer. Modbus failures increment it; any successful read resets it to zero. After 3 consecutive failures the process calls `sys.exit(1)`.
- **Register function codes:** Input registers (`0x3xxx`) use FC4; holding registers (`0x9xxx`) use FC3.
- **32-bit power values:** `low | (high << 16)` — low word first, high word second. This is the EPEVER convention.
- **Register count limits on Tracer 3210A:** `0x3100` max 18, `0x3300` max 20, `0x3000` entirely unsupported. Requesting more triggers exception 02 which corrupts the buffer.
- **Serial timeout:** Must be at least 500 ms. The 45-byte statistics response (0x3300 × 20) has a mid-frame pause while the controller reads from internal memory; 200 ms causes truncation failures.

---

## Common tasks

**Change the polling interval**
Edit the `GLib.timeout_add(1000, self._update)` call in `DbusEpever.__init__`. The value is in milliseconds.

**Add a new DBus path**
1. Call `self._dbusservice.add_path(...)` in `__init__`.
2. Assign to it in `_update` after reading the relevant register.
3. Reference `epsolar_modbus_protocol_map.md` for the register address and scaling.

**Change the Modbus slave address**
The address `1` is the second argument to `minimalmodbus.Instrument(port, 1)`. Some EPEVER controllers ship with a different default address — check the controller display menu.

**Deploy a change to Venus OS**
1. Edit the file locally.
2. `scp driver/dbus-epever-tracer.py root@<device-ip>:/data/dbus-epever-tracer/driver/`
3. `ssh root@<device-ip> svc -t /service/dbus-epever-tracer.ttyUSB0`

**Install / update / remove on device**
Run `setup-epever-driver.sh` on the Venus OS device. It auto-detects whether the driver is installed and offers install, update, or remove.

**Sync the controller clock**
```sh
svc -d /service/dbus-epever-tracer.ttyUSB0
python3 /data/dbus-epever-tracer/tools/epever-update-clock.py
svc -u /service/dbus-epever-tracer.ttyUSB0
```
