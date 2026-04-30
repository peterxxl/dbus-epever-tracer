#!/usr/bin/env python3
"""
EPEVER Tracer — Set Controller Real-Time Clock

Reads the controller's current clock, shows the drift against the system
clock, writes the current system time to the controller, then reads back
and confirms.

Usage:
  python3 epever-update-clock.py [port] [slave_addr]

Examples:
  python3 epever-update-clock.py
  python3 epever-update-clock.py /dev/ttyUSB0
  python3 epever-update-clock.py /dev/ttyUSB0 1
"""

import sys
import os
import time
from datetime import datetime, timezone

_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(_DIR, '../ext'))

def _apply_venus_timezone():
    """Read timezone from Venus OS DBus and apply it so Python uses local time.

    Venus OS stores the timezone in its own DBus settings rather than the
    standard /etc/localtime, so Python's C library sees UTC unless we set
    TZ explicitly.  This is a no-op on non-Venus systems or if TZ is
    already set.
    """
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
from epever_rtc import read_clock, write_clock

# ─── CLI args ─────────────────────────────────────────────────────────────────

args  = [a for a in sys.argv[1:] if not a.startswith('--')]
PORT  = args[0] if len(args) > 0 else '/dev/ttyUSB0'
SLAVE = int(args[1]) if len(args) > 1 else 1

# ─── ANSI colours ─────────────────────────────────────────────────────────────

R  = '\033[91m'
G  = '\033[92m'
Y  = '\033[93m'
W  = '\033[97m'
BD = '\033[1m'
DM = '\033[2m'
RS = '\033[0m'

# ─── Helpers ──────────────────────────────────────────────────────────────────

def local_now():
    """Return current local time as a timezone-aware datetime.

    datetime.now(timezone.utc).astimezone() always resolves to true local
    time via the system timezone database, regardless of whether the TZ
    environment variable is set (common on Venus OS service processes).
    """
    return datetime.now(timezone.utc).astimezone()

def drift_label(drift_sec):
    drift_abs = abs(drift_sec)
    sign      = '+' if drift_sec >= 0 else '-'
    dc        = G if drift_abs < 60 else (Y if drift_abs < 300 else R)
    return f"{dc}{sign}{drift_abs} s{RS}", drift_abs

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    now      = local_now()
    tz_name  = now.strftime('%Z')
    print(f"\n  {BD}{W}EPEVER Tracer — Update Clock{RS}   {DM}{PORT}  slave={SLAVE}  tz={tz_name}{RS}\n")

    instr = minimalmodbus.Instrument(PORT, SLAVE)
    instr.serial.baudrate = 115200
    instr.serial.bytesize = 8
    instr.serial.parity   = 'N'
    instr.serial.stopbits = 1
    instr.serial.timeout  = 0.5
    instr.mode = minimalmodbus.MODE_RTU
    instr.serial.reset_input_buffer()
    time.sleep(0.1)
    instr.serial.reset_input_buffer()

    # ── Read current controller clock ─────────────────────────────────────────
    print(f"  Reading controller clock...")
    ctrl_dt = read_clock(instr)
    now     = local_now()

    if ctrl_dt is None:
        print(f"  {R}Failed to read controller clock. Is the device connected?{RS}\n")
        sys.exit(1)

    # Both are local time; compare directly as naive datetimes.
    drift_sec        = int((now.replace(tzinfo=None) - ctrl_dt).total_seconds())
    dl, drift_abs    = drift_label(drift_sec)

    print(f"\n  {'Before':─<54}")
    print(f"  {'Controller':12s}  {ctrl_dt.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  {'System':12s}  {now.strftime('%Y-%m-%d %H:%M:%S')}   [{dl}{DM}]{RS}")

    if drift_abs == 0:
        print(f"\n  {G}Clock is already in sync. Nothing to do.{RS}\n")
        sys.exit(0)

    # ── Confirm ───────────────────────────────────────────────────────────────
    print()
    try:
        answer = input(f"  Set controller clock to system time? [y/N] ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print(f"\n  Cancelled.\n")
        sys.exit(0)

    if answer != 'y':
        print(f"  Cancelled.\n")
        sys.exit(0)

    # ── Write ─────────────────────────────────────────────────────────────────
    write_dt = local_now()
    try:
        write_clock(instr, write_dt)
    except Exception as e:
        print(f"\n  {R}Write failed: {e}{RS}\n")
        sys.exit(1)

    time.sleep(0.5)

    # ── Read back and confirm ─────────────────────────────────────────────────
    ctrl_dt2      = read_clock(instr)
    now2          = local_now()

    print(f"\n  {'After':─<54}")
    if ctrl_dt2:
        drift_sec2    = int((now2.replace(tzinfo=None) - ctrl_dt2).total_seconds())
        dl2, drift_abs2 = drift_label(drift_sec2)
        print(f"  {'Controller':12s}  {ctrl_dt2.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  {'System':12s}  {now2.strftime('%Y-%m-%d %H:%M:%S')}   [{dl2}{DM}]{RS}")
        if drift_abs2 <= 2:
            print(f"\n  {G}{BD}Clock updated successfully.{RS}\n")
        else:
            print(f"\n  {Y}Clock written but residual drift is {drift_abs2} s — re-run to tighten.{RS}\n")
    else:
        print(f"  {Y}Could not read back clock to verify.{RS}\n")

if __name__ == '__main__':
    main()
