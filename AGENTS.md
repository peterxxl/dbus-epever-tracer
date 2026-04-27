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
| `install.sh` | First-time installer for Venus OS |
| `update.sh` | In-place updater; same as install but uses `ln -sf` |
| `epsolar_modbus_protocol_map.md` | Full EPEVER LS-B register map — the primary hardware reference |
| `serial-starter.rules.default` | Example udev rules; the installer appends a rule to the live file |

The Victron `velib_python` library is **not** in this repo. The installer downloads it at runtime and places it at `ext/velib_python/` relative to the driver directory. The driver adds that path to `sys.path` before importing `vedbus`.

---

## Modbus register blocks read every second

| Variable | Start address | Count | Content |
|---|---|---|---|
| `c3100` | `0x3100` | 18 | PV voltage/current/power, battery voltage/current/temp, load data |
| `c3200` | `0x3200` | 3 | Battery status flags, charging status flags, load on/off |
| `c3300` | `0x3300` | 20 | Historical max/min voltages, total generated energy |
| `c330C` | `0x330C` | 2 | Today's generated energy (kWh × 100) |
| `boostchargingvoltage` | `0x9002` | 2 | Boost and float voltage setpoints (V × 100) |

All voltage, current, and power values are stored as integers scaled by 100 (e.g. 2450 = 24.50 V). Divide by 100 to get SI units.

Power values wider than 16 bits use two consecutive registers: `low | (high << 8)`.

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

The driver accumulates today's statistics entirely in memory (no persistent storage). On each update tick it checks `datetime.now().day`; when the day changes it:

1. Copies today's DBus values to the `_yesterday_*` attributes and to the `/History/Daily/1/*` DBus paths.
2. Resets today's accumulators and the `/History/Daily/0/*` max/min paths to zero.

Time-in-phase (`_time_in_bulk`, `_time_in_absorption`, `_time_in_float`) is accumulated in floating-point minutes and rounded to whole minutes before being written to DBus.

**Implication:** a driver restart loses the current day's accumulated time-in-phase and max/min statistics. This is a known limitation.

---

## DBus service name and device instance

The service name is `com.victronenergy.solarcharger.<port>` where `<port>` is the last component of the serial device path (e.g. `ttyUSB0`). This means multiple instances can run concurrently on different ports.

The device instance (`deviceinstance = 278`) is the number shown in VRM. Change it if another device on the same system already uses 278.

---

## Dependencies

| Dependency | Source | Notes |
|---|---|---|
| `minimalmodbus` | pip (`pip3 install minimalmodbus`) | Modbus RTU client |
| `dbus-python` | Venus OS system package | DBus bindings |
| `PyGObject` (GLib) | Venus OS system package | Main event loop |
| `pyserial` | installed with minimalmodbus | Serial port I/O |
| `velib_python` (vedbus) | Downloaded by installer from GitHub | Victron DBus helper |

Do not add new runtime dependencies without updating `install.sh` and `update.sh`.

---

## Testing and validation

There is no automated test suite. The only way to validate a change is to run it on real hardware (Venus OS + EPEVER controller). When working without hardware:

- Use `minimalmodbus`'s debug mode or a Modbus simulator to supply synthetic register data.
- Read the log output from `/var/log/dbus-epever-tracer.ttyUSBx/current` on the device.
- Use `dbus-spy` or `dbus-monitor` on the Venus OS device to inspect live DBus values.

---

## Things to watch out for

- **Python version:** Venus OS ships Python 3. The shebang is `#!/usr/bin/env python3`. Do not use Python 2 syntax.
- **Single-file constraint:** The driver is intentionally one file. Do not split it into a package without updating `install.sh`, `update.sh`, and the start script.
- **No persistent state:** Statistics survive only while the process is running. Do not assume data from a previous run is available.
- **Serial port from CLI:** The serial port path is `sys.argv[1]`. The Modbus instrument and the DBus service name are both derived from it at module level (outside any function), so they are set once at import time.
- **Exception counter is global:** `exceptionCounter` is a module-level integer. Modbus failures increment it; any successful read resets it to zero. After 3 consecutive failures the process calls `sys.exit(1)`.
- **Register function code:** All reads use function code 4 (`read_registers(addr, count, 4)`) for input registers, except the boost voltage which uses function code 3 (`read_registers(addr, count, 3)`) for holding registers.
- **32-bit power values:** `c3100[2] | c3100[3] << 8` — the low word comes first, high word second. This is the EPEVER convention and differs from standard big-endian Modbus.
- **Minimum PV voltage:** The driver clamps `c3100[0]` to 1 before any calculations to avoid division by zero. This is not used in a division currently but is a guard for future code.

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
