#!/usr/bin/env python3
"""
EPEVER Tracer — Configuration Tool

Reads all writable controller parameters, shows current values alongside
allowed ranges or options, and lets you change any parameter interactively.
After writing, the tool reads the register back and confirms the value was
accepted by the controller.

Usage:
  python3 epever-config.py [port] [slave_addr]

Examples:
  python3 epever-config.py
  python3 epever-config.py /dev/ttyUSB0
  python3 epever-config.py /dev/ttyUSB0 1
"""

import sys
import os
import time

_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(_DIR, '../ext'))


def _apply_venus_timezone():
    if os.environ.get('TZ'):
        return
    try:
        import dbus
        obj = dbus.SystemBus().get_object(
            'com.victronenergy.settings', '/Settings/System/TimeZone')
        tz = str(obj.GetValue())
        if tz:
            os.environ['TZ'] = tz
            time.tzset()
    except Exception:
        pass

_apply_venus_timezone()

import minimalmodbus

# ─── CLI args ─────────────────────────────────────────────────────────────────

args  = sys.argv[1:]
PORT  = args[0] if len(args) > 0 else '/dev/ttyUSB0'
SLAVE = int(args[1]) if len(args) > 1 else 1

# ─── ANSI colours ─────────────────────────────────────────────────────────────

R  = '\033[91m'
G  = '\033[92m'
Y  = '\033[93m'
C  = '\033[96m'
W  = '\033[97m'
BD = '\033[1m'
DM = '\033[2m'
RS = '\033[0m'

# ─── Parameter definitions ────────────────────────────────────────────────────
#
# Each entry is a dict:
#   addr    – Modbus holding register address (FC03 read / FC06 or FC10 write)
#   name    – Human-readable label
#   type    – 'voltage' | 'int' | 'enum' | 'pct' | 'temp'
#   scale   – divide register value by this to get display value (1 = raw)
#   unit    – display unit string
#   lo/hi   – allowed range (inclusive) in display units (None = no hard limit)
#   options – list of (raw_value, label) for enum types
#   hint    – optional extra guidance shown when editing

PARAMS = [
    # ── Battery bank ──────────────────────────────────────────────────────────
    {
        'addr': 0x9000,
        'name': 'Battery type',
        'type': 'enum',
        'scale': 1, 'unit': '',
        'options': [(0, 'User defined'), (1, 'Sealed'), (2, 'GEL'), (3, 'Flooded')],
        'hint': 'Changing type reloads factory voltage presets from the controller.',
    },
    {
        'addr': 0x9001,
        'name': 'Battery capacity',
        'type': 'int',
        'scale': 1, 'unit': 'Ah',
        'lo': 1, 'hi': 9999,
        'hint': 'Rated capacity of your battery bank.',
    },
    {
        'addr': 0x9067,
        'name': 'Battery rated voltage',
        'type': 'enum',
        'scale': 1, 'unit': '',
        'options': [(0, 'Auto-detect'), (1, '12 V'), (2, '24 V'), (3, '36 V'),
                    (4, '48 V'), (5, '60 V'), (6, '110 V'), (7, '120 V'),
                    (8, '220 V'), (9, '240 V')],
        'hint': 'Auto-detect works for most installations.',
    },
    {
        'addr': 0x9070,
        'name': 'Battery management mode',
        'type': 'enum',
        'scale': 1, 'unit': '',
        'options': [(0, 'Voltage compensation'), (1, 'SOC')],
        'hint': 'SOC mode requires a current sensor; use Voltage compensation otherwise.',
    },
    # ── Charging voltage thresholds ───────────────────────────────────────────
    {
        'addr': 0x9003,
        'name': 'High voltage disconnect',
        'type': 'voltage',
        'scale': 100, 'unit': 'V',
        'lo': 9.0, 'hi': 32.0,
        'hint': 'Charging stops when battery reaches this voltage.',
    },
    {
        'addr': 0x9004,
        'name': 'Charging limit voltage',
        'type': 'voltage',
        'scale': 100, 'unit': 'V',
        'lo': 9.0, 'hi': 32.0,
        'hint': 'Maximum voltage during any charging stage.',
    },
    {
        'addr': 0x9005,
        'name': 'Overvoltage reconnect',
        'type': 'voltage',
        'scale': 100, 'unit': 'V',
        'lo': 9.0, 'hi': 32.0,
        'hint': 'Charging resumes after a high-voltage disconnect when battery drops to this.',
    },
    {
        'addr': 0x9006,
        'name': 'Equalization voltage',
        'type': 'voltage',
        'scale': 100, 'unit': 'V',
        'lo': 9.0, 'hi': 32.0,
        'hint': 'Voltage used during equalization (not applicable to GEL batteries).',
    },
    {
        'addr': 0x9007,
        'name': 'Boost / absorption voltage',
        'type': 'voltage',
        'scale': 100, 'unit': 'V',
        'lo': 9.0, 'hi': 32.0,
        'hint': 'Target voltage for bulk/boost and absorption charging phases.',
    },
    {
        'addr': 0x9008,
        'name': 'Float voltage',
        'type': 'voltage',
        'scale': 100, 'unit': 'V',
        'lo': 9.0, 'hi': 32.0,
        'hint': 'Maintenance voltage after the battery is fully charged.',
    },
    {
        'addr': 0x9009,
        'name': 'Boost reconnect voltage',
        'type': 'voltage',
        'scale': 100, 'unit': 'V',
        'lo': 9.0, 'hi': 32.0,
        'hint': 'Controller restarts boost charging when battery drops to this during float.',
    },
    # ── Low-voltage thresholds ────────────────────────────────────────────────
    {
        'addr': 0x900A,
        'name': 'Low voltage reconnect',
        'type': 'voltage',
        'scale': 100, 'unit': 'V',
        'lo': 9.0, 'hi': 32.0,
        'hint': 'Load output turns back on when battery recovers to this voltage.',
    },
    {
        'addr': 0x900B,
        'name': 'Undervoltage warning reconnect',
        'type': 'voltage',
        'scale': 100, 'unit': 'V',
        'lo': 9.0, 'hi': 32.0,
        'hint': 'Undervoltage warning clears when battery rises to this voltage.',
    },
    {
        'addr': 0x900C,
        'name': 'Undervoltage warning',
        'type': 'voltage',
        'scale': 100, 'unit': 'V',
        'lo': 9.0, 'hi': 32.0,
        'hint': 'Warning triggered when battery drops below this voltage.',
    },
    {
        'addr': 0x900D,
        'name': 'Low voltage disconnect',
        'type': 'voltage',
        'scale': 100, 'unit': 'V',
        'lo': 9.0, 'hi': 32.0,
        'hint': 'Load output turns off when battery drops to this voltage.',
    },
    {
        'addr': 0x900E,
        'name': 'Discharging limit voltage',
        'type': 'voltage',
        'scale': 100, 'unit': 'V',
        'lo': 9.0, 'hi': 32.0,
        'hint': 'Absolute minimum battery voltage; load disconnect is enforced below this.',
    },
    # ── Temperature ───────────────────────────────────────────────────────────
    {
        'addr': 0x9002,
        'name': 'Temperature compensation',
        'type': 'int',
        'scale': 100, 'unit': 'mV/°C/2V',
        'lo': 0, 'hi': 9,
        'hint': 'Voltage adjustment per °C per 2 V of battery. Typical: 3–5 for flooded, 0 for lithium.',
    },
    {
        'addr': 0x9017,
        'name': 'Battery temp warning high',
        'type': 'temp',
        'scale': 100, 'unit': '°C',
        'lo': 0, 'hi': 100,
        'hint': 'Warning issued when battery temperature exceeds this value.',
    },
    {
        'addr': 0x9018,
        'name': 'Battery temp warning low',
        'type': 'temp',
        'scale': 100, 'unit': '°C',
        'lo': -50, 'hi': 50,
        'signed': True,
        'hint': 'Warning issued when battery temperature falls below this value.',
    },
    {
        'addr': 0x9019,
        'name': 'Controller temp limit high',
        'type': 'temp',
        'scale': 100, 'unit': '°C',
        'lo': 0, 'hi': 100,
        'hint': 'Charging stops when controller internal temperature exceeds this.',
    },
    {
        'addr': 0x901A,
        'name': 'Controller temp recovery',
        'type': 'temp',
        'scale': 100, 'unit': '°C',
        'lo': 0, 'hi': 100,
        'hint': 'Charging resumes when controller temperature drops below this.',
    },
    # ── Timing ────────────────────────────────────────────────────────────────
    {
        'addr': 0x906C,
        'name': 'Boost duration',
        'type': 'int',
        'scale': 1, 'unit': 'min',
        'lo': 10, 'hi': 180,
        'hint': 'How long the controller stays in boost/absorption phase. Typical: 60–120 min.',
    },
    {
        'addr': 0x906B,
        'name': 'Equalization duration',
        'type': 'int',
        'scale': 1, 'unit': 'min',
        'lo': 10, 'hi': 180,
        'hint': 'How long the equalization phase lasts. Typical: 60–120 min.',
    },
    {
        'addr': 0x9016,
        'name': 'Equalization cycle',
        'type': 'int',
        'scale': 1, 'unit': 'days',
        'lo': 0, 'hi': 365,
        'hint': 'Days between automatic equalization. 0 = disabled.',
    },
    # ── Sun detection ─────────────────────────────────────────────────────────
    {
        'addr': 0x901E,
        'name': 'Night threshold voltage (NTTV)',
        'type': 'voltage',
        'scale': 100, 'unit': 'V',
        'lo': 0.0, 'hi': 30.0,
        'hint': 'PV voltage below this value signals nighttime.',
    },
    {
        'addr': 0x901F,
        'name': 'Night detection delay',
        'type': 'int',
        'scale': 1, 'unit': 'min',
        'lo': 1, 'hi': 60,
        'hint': 'PV must stay below NTTV for this long to confirm nighttime.',
    },
    {
        'addr': 0x9020,
        'name': 'Day threshold voltage (DTTV)',
        'type': 'voltage',
        'scale': 100, 'unit': 'V',
        'lo': 0.0, 'hi': 30.0,
        'hint': 'PV voltage above this value signals daytime.',
    },
    {
        'addr': 0x9021,
        'name': 'Day detection delay',
        'type': 'int',
        'scale': 1, 'unit': 'min',
        'lo': 1, 'hi': 60,
        'hint': 'PV must stay above DTTV for this long to confirm daytime.',
    },
    # ── Load control ──────────────────────────────────────────────────────────
    {
        'addr': 0x903D,
        'name': 'Load control mode',
        'type': 'enum',
        'scale': 1, 'unit': '',
        'options': [
            (0, 'Manual'),
            (1, 'Light ON/OFF'),
            (2, 'Light ON + Timer'),
            (3, 'Time Control'),
        ],
        'hint': 'Manual: toggle via coil 0x0002. Light ON/OFF: follows day/night detection.',
    },
    {
        'addr': 0x906A,
        'name': 'Default load state (manual mode)',
        'type': 'enum',
        'scale': 1, 'unit': '',
        'options': [(0, 'Off'), (1, 'On')],
        'hint': 'State the load output defaults to on power-up in manual mode.',
    },
]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _to_signed(raw):
    """Interpret a 16-bit unsigned register value as signed."""
    return raw - 65536 if raw >= 32768 else raw


def _to_unsigned(signed_raw):
    """Convert a signed integer back to a 16-bit unsigned register value."""
    return signed_raw + 65536 if signed_raw < 0 else signed_raw


def fmt_value(p, raw):
    """Format a raw register value for display."""
    if p['type'] == 'enum':
        label = next((lbl for val, lbl in p['options'] if val == raw), f'unknown ({raw})')
        return label
    if p.get('signed'):
        raw = _to_signed(raw)
    val = raw / p['scale']
    if p['type'] in ('voltage', 'temp'):
        return f'{val:.2f} {p["unit"]}'
    return f'{val:g} {p["unit"]}'


def fmt_range(p):
    """Format the allowed range or options list for display."""
    if p['type'] == 'enum':
        return '  |  '.join(f'{v}={lbl}' for v, lbl in p['options'])
    lo = p.get('lo')
    hi = p.get('hi')
    if lo is not None and hi is not None:
        return f'{lo} – {hi} {p["unit"]}'
    if lo is not None:
        return f'≥ {lo} {p["unit"]}'
    if hi is not None:
        return f'≤ {hi} {p["unit"]}'
    return ''


def read_param(instr, p):
    """Read one parameter from the controller. Returns raw register value or None."""
    try:
        vals = instr.read_registers(p['addr'], 1, 3)
        return vals[0]
    except Exception as e:
        return None


def write_and_verify(instr, p, raw_new):
    """Write raw_new to the register, read back, return (ok, raw_readback).

    raw_new is in the same domain as read_param returns (unsigned 16-bit).
    For signed parameters the caller passes the unsigned two's-complement value.
    """
    instr.write_registers(p['addr'], [raw_new])
    time.sleep(0.15)
    raw_back = read_param(instr, p)
    return raw_back == raw_new, raw_back


# ─── Display ──────────────────────────────────────────────────────────────────

def print_header(values):
    print()
    print(f'  {BD}{W}EPEVER Tracer Configuration{RS}  '
          f'{DM}port {PORT}  slave {SLAVE}{RS}')
    print()
    col_w = 34
    print(f'  {DM}  #  {"Parameter":<{col_w}} {"Current value":<18} Allowed range / options{RS}')
    print(f'  {DM}  {"─" * (col_w + 44)}{RS}')
    for i, p in enumerate(PARAMS):
        raw = values[i]
        num = f'{i + 1:>3}.'
        name = p['name']
        if raw is None:
            cur = f'{R}read error{RS}'
        else:
            cur = f'{W}{fmt_value(p, raw)}{RS}'
        rng = f'{DM}{fmt_range(p)}{RS}'
        print(f'  {DM}{num}{RS}  {C}{name:<{col_w}}{RS} {cur:<28} {rng}')
    print()


# ─── Edit flow ────────────────────────────────────────────────────────────────

def edit_param(instr, p, raw_current):
    print()
    print(f'  {BD}{W}{p["name"]}{RS}  {DM}(register 0x{p["addr"]:04X}){RS}')
    if p.get('hint'):
        print(f'  {DM}{p["hint"]}{RS}')
    print()

    if raw_current is not None:
        print(f'  Current value : {W}{fmt_value(p, raw_current)}{RS}')
    else:
        print(f'  Current value : {R}could not be read{RS}')

    print(f'  Allowed       : {fmt_range(p)}')
    print()

    if p['type'] == 'enum':
        for val, lbl in p['options']:
            marker = f'{G}*{RS}' if val == raw_current else ' '
            print(f'    {marker} {val} — {lbl}')
        print()
        try:
            raw_input = input(f'  Enter option number (or Enter to cancel): ').strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not raw_input:
            return
        try:
            raw_new = int(raw_input)
        except ValueError:
            print(f'  {R}Not a valid number.{RS}')
            return
        valid_vals = [v for v, _ in p['options']]
        if raw_new not in valid_vals:
            print(f'  {R}Value {raw_new} is not one of the available options.{RS}')
            return
    else:
        # Numeric entry
        try:
            user_input = input(f'  Enter new value in {p["unit"]} (or Enter to cancel): ').strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not user_input:
            return
        try:
            user_val = float(user_input)
        except ValueError:
            print(f'  {R}Not a valid number.{RS}')
            return

        lo = p.get('lo')
        hi = p.get('hi')
        if lo is not None and user_val < lo:
            print(f'  {R}Value {user_val} is below the minimum ({lo} {p["unit"]}).{RS}')
            return
        if hi is not None and user_val > hi:
            print(f'  {R}Value {user_val} is above the maximum ({hi} {p["unit"]}).{RS}')
            return

        raw_new = round(user_val * p['scale'])
        if p.get('signed'):
            raw_new = _to_unsigned(raw_new)

    display_new = fmt_value(p, raw_new)
    try:
        confirm = input(f'  Write {W}{display_new}{RS} to controller? [y/N]: ').strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if confirm != 'y':
        print(f'  {DM}Cancelled.{RS}')
        return

    print(f'  Writing… ', end='', flush=True)
    try:
        ok, raw_back = write_and_verify(instr, p, raw_new)
    except Exception as e:
        print(f'{R}error: {e}{RS}')
        return

    if ok:
        print(f'{G}OK{RS}  controller confirmed {W}{fmt_value(p, raw_back)}{RS}')
    else:
        if raw_back is None:
            print(f'{Y}written but could not read back for verification{RS}')
        else:
            print(f'{R}MISMATCH{RS}  wrote {display_new} but controller returned '
                  f'{W}{fmt_value(p, raw_back)}{RS}')


# ─── Main loop ────────────────────────────────────────────────────────────────

def main():
    print(f'\n  Connecting to {PORT} slave {SLAVE}…', end='', flush=True)
    try:
        instr = minimalmodbus.Instrument(PORT, SLAVE)
        instr.serial.baudrate = 115200
        instr.serial.timeout  = 1.0
        instr.mode = minimalmodbus.MODE_RTU
        instr.serial.reset_input_buffer()
        time.sleep(0.1)
        instr.serial.reset_input_buffer()
    except Exception as e:
        print(f'  {R}failed: {e}{RS}\n')
        sys.exit(1)
    print(f'  {G}connected{RS}')

    while True:
        # Read all parameters
        print(f'\n  {DM}Reading parameters…{RS}', end='\r')
        values = [read_param(instr, p) for p in PARAMS]

        print_header(values)

        try:
            choice = input(f'  Enter parameter number to edit, '
                           f'{W}r{RS} to refresh, or {W}q{RS} to quit: ').strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if choice == 'q':
            break
        if choice == 'r' or choice == '':
            continue

        try:
            idx = int(choice) - 1
        except ValueError:
            print(f'  {R}Enter a number, r, or q.{RS}')
            continue

        if idx < 0 or idx >= len(PARAMS):
            print(f'  {R}Number out of range.{RS}')
            continue

        edit_param(instr, PARAMS[idx], values[idx])

        # After editing, pause briefly so the user can read the result
        try:
            input(f'\n  Press Enter to continue…')
        except (EOFError, KeyboardInterrupt):
            pass

    print(f'\n  {DM}Done.{RS}\n')


if __name__ == '__main__':
    main()
