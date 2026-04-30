# AGENTS.md — guidance for AI coding agents

This file tells AI coding assistants (Claude Code, GitHub Copilot, etc.) the things they need to know about this repository that are not obvious from reading the code.

---

## What this project is

A single-file Python 3 driver that runs on a Victron Venus OS device and makes an EPEVER Tracer MPPT solar charge controller visible to the Victron ecosystem (GX display, Modbus-TCP gateway, VRM portal, etc.).

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
com.victronenergy.temperature.ttyUSBx   (system DBus service)
com.victronenergy.switch.ttyUSBx        (system DBus service)
     │
Venus OS device (Cerbo GX, etc.)
     │ GX display / Modbus-TCP / Node-RED / …
     │
VRM portal (remote, via internet)
```

**VRM** (Victron Remote Management) is the cloud portal — it is not the local device. When referring to what the user sees locally, say "Venus OS device" or "GX display".

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
| `epsolar_modbus_protocol_map.md` | Full EPEVER register map with ranges, observed 24 V defaults, source annotations, and Tracer 3210A compatibility notes |
| `serial-starter.rules.default` | Example udev rules; the installer appends a rule to the live file |
| `tools/epever-monitor.py` | Standalone live terminal monitor — reads all register blocks, colour-coded display, `--dump` mode for raw frame capture |
| `tools/epever-config.py` | Interactive configuration tool — reads all writable holding registers, shows ranges/options, writes and verifies |
| `tools/epever-update-clock.py` | Reads the controller RTC, shows drift vs system clock, optionally writes system time to controller |
| `tools/epever_rtc.py` | Shared RTC register helpers (`read_clock`, `write_clock`) imported by both the driver and the tools |

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
| `charge_voltages` | `0x9007` | 3 | 3 | Boost setpoint (0x9007), float setpoint (0x9008), boost reconnect (0x9009) |
| `boost_duration_reg` | `0x906C` | 1 | 3 | Boost duration in minutes |

**Tracer 3210A register limits** — requesting more registers than listed above returns Modbus exception 02 and corrupts the serial buffer for subsequent reads. See `epsolar_modbus_protocol_map.md` for full compatibility notes.

All voltage, current, and power values are stored as integers scaled by 100 (e.g. 2450 = 24.50 V). Divide by 100 to get SI units.

32-bit power values use two consecutive registers: `low | (high << 16)`.

Registers `0x311A`, `0x311B`, and `0x311D` (SOC, remote battery temp, system rated voltage) must be read **one at a time** — reading them as a block causes cascade failures on the Tracer 3210A.

**Signed registers** — some holding registers use signed 16-bit encoding (two's complement). Notable example: battery temp warning low (0x9018). Raw value 0xF060 = 61536 unsigned = −4000 signed = −40.00 °C. Always apply `signed16()` / two's complement conversion for temperature registers that can go negative.

---

## Serial port startup flush

On startup the driver calls `controller.serial.reset_input_buffer()` twice with a 100 ms sleep between them. This drains any bytes left in the FT232R USB FIFO from a previous session, which would otherwise arrive during the first read and cause a checksum error.

---

## Venus OS timezone

Venus OS stores the active timezone in DBus (`com.victronenergy.settings /Settings/System/TimeZone`), not in `/etc/localtime`. Service processes do not have the `TZ` environment variable set, so Python's `datetime.now()` returns UTC unless you apply the timezone first.

The driver and all tools call `_apply_venus_timezone()` which reads the DBus setting and calls `time.tzset()`. **In the driver this must be called inside `main()` after `DBusGMainLoop(set_as_default=True)`** — calling `dbus.SystemBus()` before the main loop is registered creates a cached shared connection without a main loop, which then causes `VeDbusService` to raise a `RuntimeError`.

---

## Automatic controller clock sync

On startup, `_sync_controller_clock()` is called from `main()` after `_apply_venus_timezone()` and before `DbusEpever()` is instantiated. It reads the controller RTC via `read_clock()`, computes drift against local system time, and if the absolute drift exceeds 60 seconds it writes the current time with `write_clock()` and reads back to confirm.

The shared helpers `read_clock(ctrl)` and `write_clock(ctrl, dt)` live in `tools/epever_rtc.py`. The driver imports them by inserting `../tools` into `sys.path`. The tools import them with `sys.path.insert(0, _DIR)` where `_DIR` is the directory of the tool script.

---

## Charging state mapping

EPEVER encodes the charging phase in bits 3–2 of register `0x3201`:

| Bits [3,2] | EPEVER meaning | Victron state |
|---|---|---|
| 00 | Not charging | 0 (Off) |
| 01 | Float | 5 (Float) |
| 10 | Boost | 3 (Bulk) |
| 11 | Equalising | 6 (Storage) |

### Absorption detection

EPEVER has no separate absorption state — "Boost" covers both Bulk and Absorption. The driver uses a state machine to split them:

- **Enter absorption**: EPEVER in Boost AND battery voltage ≥ `charge_voltages[0] / 100` (register 0x9007, boost/absorption setpoint).
- **Stay in absorption**: elapsed time since entry < boost duration (0x906C minutes) AND battery voltage ≥ boost reconnect voltage (0x9009).
- **Exit absorption**: voltage drops below boost reconnect threshold (heavy load / cloud cover), boost duration elapses, or EPEVER leaves Boost phase.

`_absorption_start_time` (epoch seconds) is persisted in `state.json` so a driver restart during an ongoing absorption session resumes correctly.

---

## Error mapping

`map_epever_error(batt_status, chg_status)` converts EPEVER status bits to a Victron MPPT error code. Only a subset of Victron codes is used because EPEVER exposes fewer fault conditions. The mapping is defined in `ERROR_MAP` at module level.

---

## Daily statistics and midnight rollover

**Yield, max PV voltage, min/max battery voltage** — these are tracked in driver memory (`_daily_yield`, `_daily_max_pv_v`, `_daily_min_batt_v`, `_daily_max_batt_v`) using a max/min guard: the in-memory value is only updated when the register value is higher (for max) or lower (for min) than the current accumulator. The controller resets its own daily registers at its own clock midnight, which may differ from system midnight due to clock drift. Reading register values directly at rollover would capture zeros or near-zeros. Using driver-side accumulators prevents this.

**Max power and max battery current** have no controller register and are tracked in driver memory, reset at midnight.

**Time-in-phase** (`_time_in_bulk`, `_time_in_absorption`, `_time_in_float`) is accumulated in floating-point minutes and rounded to whole minutes before being written to DBus.

**Midnight rollover** — detected by comparing `datetime.now().day` to `self._last_day`. At rollover the current day's accumulators are snapshotted into `_history` with **yesterday's date** (`datetime.now() - timedelta(days=1)`), then the accumulators are reset. The snapshot must use yesterday's date because `datetime.now()` already returns the new day at the moment rollover fires.

**State persistence** — the driver saves daily accumulators (time-in-phase, max power, max battery current, daily peak values) and the full 30-day history list to a JSON file at `/data/dbus-epever-tracer/state.json` on every update tick. On startup it restores accumulators if the file's date matches today; history is always loaded regardless of date.

**Rolling history** — up to 30 previous days are stored in `self._history` (index 0 = yesterday). Published to DBus as `/History/Daily/1/` through `/History/Daily/30/`. `/History/Overall/DaysAvailable` is set to 31 (today + 30 history days).

---

## DBus service name and device instance

The service name is `com.victronenergy.solarcharger.<port>` where `<port>` is the last component of the serial device path (e.g. `ttyUSB0`). This means multiple instances can run concurrently on different ports.

All three services (solarcharger, temperature, switch) use the same device instance number. Device instance numbers are unique per product type, not globally across all product types. The instance number defaults to `278` and is loaded from `state.json` (`deviceinstance` key). It is set at install time via the setup script and can also be edited directly in `state.json`.

---

## CustomName

All three services expose `/CustomName` as a writeable DBus path. Changes are written back to `state.json` via `onchangecallback` and survive driver restarts. The switch service also exposes `/SwitchableOutput/output_1/Settings/CustomName` (writeable, persisted as `customname_output`).

Default values written at install time:

| State key | Default |
|---|---|
| `customname_charger` | Set by install script (e.g. `PV Charger`) |
| `customname_temp` | Set by install script (e.g. `PV Charger Temperature`) |
| `customname_switch` | Set by install script (e.g. `PV Charger Load Output`) |
| `customname_output` | `''` (empty — Venus OS shows the hardware name) |

**Important:** the driver writes `state.json` every second. Never edit `state.json` while the driver is running — use `svc -d` to stop it first, edit, then restart.

---

## Serial number

`self._serialnumber` is loaded from `state.json` (`serialnumber` key, default `''`). It is applied to `/Serial` on all three services and persisted through `_save_state()`. Set at install time; empty by default.

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

All tools in `tools/` require the driver to be stopped first — they cannot share the serial port with the running driver.

```sh
svc -d /service/dbus-epever-tracer.ttyUSB0   # stop
# run tool
svc -u /service/dbus-epever-tracer.ttyUSB0   # resume
```

All tools read the Venus OS timezone from `com.victronenergy.settings /Settings/System/TimeZone` via DBus so that local time is correct even when the `TZ` environment variable is not set.

### epever-monitor.py

Reads all available register blocks and displays a colour-coded live terminal UI. Supports `--dump` mode to capture one iteration of raw Modbus bytes to a timestamped file and exit. Uses `read_clock()` from `epever_rtc.py` to display the controller clock and drift.

### epever-config.py

Interactive menu-driven tool for reading and writing all writable holding registers (0x9000 range). Each parameter entry has a type (`voltage`, `int`, `enum`, `temp`), scale, unit, allowed range or options list, and an optional `signed=True` flag for registers that use two's complement encoding. The parameter list includes the register address. After writing, the register is read back to verify the controller accepted the value.

### epever-update-clock.py

Reads the controller RTC via `read_clock()` (from `epever_rtc.py`), compares it to system local time, colour-codes the drift, and optionally writes all three RTC registers atomically via `write_clock()`.

### epever_rtc.py

Shared module — not a standalone tool. Provides:

- `read_clock(ctrl)` — reads registers 0x9013–0x9015 (FC3) and returns a naive `datetime` in local time, or `None` on failure.
- `write_clock(ctrl, dt)` — encodes a `datetime` and writes it to registers 0x9013–0x9015 atomically via FC10.

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
- **Signed 16-bit registers:** Temperature registers that can go negative (e.g. 0x9018 battery temp warning low) use two's complement. Reading as unsigned gives wrong values. Apply `signed16()` on read; convert back to unsigned two's complement before writing.
- **DBus main loop order:** `_apply_venus_timezone()` calls `dbus.SystemBus()`. This must happen after `DBusGMainLoop(set_as_default=True)` in `main()`. Calling it at module load time caches a main-loop-less connection and breaks `VeDbusService`.
- **state.json and the running driver:** The driver writes `state.json` every second. If you write to `state.json` while the driver is running, the driver will overwrite your changes within a second. Always stop the driver with `svc -d` before editing `state.json` directly.
- **Daily peak accumulators vs controller registers:** Do not replace the driver-side `_daily_max_pv_v` / `_daily_min_batt_v` / `_daily_yield` accumulators with direct register reads at rollover. The controller resets its own registers at its own clock midnight, which can precede system midnight; reading at that moment captures zeroed values. The accumulator pattern (update only when register value is a new extreme) prevents this.

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

**Change device name, serial number, or VRM instance after install**
Stop the driver, edit `/data/dbus-epever-tracer/state.json` directly, then restart:
```sh
svc -d /service/dbus-epever-tracer.ttyUSB0
# edit /data/dbus-epever-tracer/state.json
svc -t /service/serial-starter
```
Or write to the `/CustomName` DBus path from any Victron tool — changes are saved to `state.json` automatically.

**Sync the controller clock**
The driver syncs automatically on startup. To sync manually:
```sh
svc -d /service/dbus-epever-tracer.ttyUSB0
python3 /data/dbus-epever-tracer/tools/epever-update-clock.py
svc -u /service/dbus-epever-tracer.ttyUSB0
```

**Configure controller parameters**
```sh
svc -d /service/dbus-epever-tracer.ttyUSB0
python3 /data/dbus-epever-tracer/tools/epever-config.py
svc -u /service/dbus-epever-tracer.ttyUSB0
```
