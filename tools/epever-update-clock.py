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

_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(_DIR, '../ext'))

import minimalmodbus

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

def read_clock(instr):
    """Return (clock_str, struct_time) or (None, None) on failure."""
    try:
        regs = instr.read_registers(0x9013, 3, 3)
        sec  =  regs[0] & 0xFF
        mn   = (regs[0] >> 8) & 0xFF
        hr   =  regs[1] & 0xFF
        day  = (regs[1] >> 8) & 0xFF
        mon  =  regs[2] & 0xFF
        yr   = (regs[2] >> 8) & 0xFF
        s    = f"20{yr:02d}-{mon:02d}-{day:02d} {hr:02d}:{mn:02d}:{sec:02d}"
        st   = time.strptime(s, '%Y-%m-%d %H:%M:%S')
        return s, st
    except Exception as e:
        return None, None

def drift_str(now_ts, ct):
    drift     = int(now_ts - time.mktime(ct))
    drift_abs = abs(drift)
    sign      = '+' if drift >= 0 else '-'
    dc        = G if drift_abs < 60 else (Y if drift_abs < 300 else R)
    return f"{dc}{sign}{drift_abs} s{RS}", drift_abs

def write_clock(instr, t):
    """Write struct_time t to the controller RTC (registers 0x9013–0x9015)."""
    reg0 = ((t.tm_min  & 0xFF) << 8) | (t.tm_sec  & 0xFF)
    reg1 = ((t.tm_mday & 0xFF) << 8) | (t.tm_hour & 0xFF)
    reg2 = ((t.tm_year % 100  ) << 8) | (t.tm_mon  & 0xFF)
    instr.write_registers(0x9013, [reg0, reg1, reg2])

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print(f"\n  {BD}{W}EPEVER Tracer — Update Clock{RS}   {DM}{PORT}  slave={SLAVE}{RS}\n")

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
    clock_str, clock_st = read_clock(instr)
    now_ts  = time.time()
    now_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now_ts))

    if clock_str is None:
        print(f"  {R}Failed to read controller clock. Is the device connected?{RS}\n")
        sys.exit(1)

    ds, drift_abs = drift_str(now_ts, clock_st)
    print(f"\n  {'Before':─<54}")
    print(f"  {'Controller':12s}  {clock_str}")
    print(f"  {'System':12s}  {now_str}   [{ds}{DM}]{RS}")

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
    now_lt = time.localtime()
    try:
        write_clock(instr, now_lt)
    except Exception as e:
        print(f"\n  {R}Write failed: {e}{RS}\n")
        sys.exit(1)

    time.sleep(0.5)

    # ── Read back and confirm ─────────────────────────────────────────────────
    clock_str2, clock_st2 = read_clock(instr)
    now_ts2  = time.time()
    now_str2 = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now_ts2))

    print(f"\n  {'After':─<54}")
    if clock_str2:
        ds2, drift_abs2 = drift_str(now_ts2, clock_st2)
        print(f"  {'Controller':12s}  {clock_str2}")
        print(f"  {'System':12s}  {now_str2}   [{ds2}{DM}]{RS}")
        if drift_abs2 <= 2:
            print(f"\n  {G}{BD}Clock updated successfully.{RS}\n")
        else:
            print(f"\n  {Y}Clock written but residual drift is {drift_abs2} s — re-run to tighten.{RS}\n")
    else:
        print(f"  {Y}Could not read back clock to verify.{RS}\n")

if __name__ == '__main__':
    main()
