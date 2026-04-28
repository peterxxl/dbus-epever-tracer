#!/usr/bin/env python3
"""
EPEVER Tracer — Live Monitor

Reads all available Modbus registers and displays them in real-time.
Useful for debugging and understanding the controller's output before
implementing new driver features.

Usage:
  python3 epever-monitor.py [port] [slave_addr] [interval_sec]

Examples:
  python3 epever-monitor.py
  python3 epever-monitor.py /dev/ttyUSB0
  python3 epever-monitor.py /dev/ttyUSB0 1 2
"""

import sys
import os
import time
import signal

# Use the bundled minimalmodbus from the ext/ directory
_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(_DIR, '../ext'))

import minimalmodbus

# ─── CLI args ─────────────────────────────────────────────────────────────────

PORT     = sys.argv[1] if len(sys.argv) > 1 else '/dev/ttyUSB0'
SLAVE    = int(sys.argv[2]) if len(sys.argv) > 2 else 1
INTERVAL = float(sys.argv[3]) if len(sys.argv) > 3 else 2.0

# ─── ANSI colours ─────────────────────────────────────────────────────────────

R  = '\033[91m'   # red
G  = '\033[92m'   # green
Y  = '\033[93m'   # yellow
B  = '\033[94m'   # blue
C  = '\033[96m'   # cyan
W  = '\033[97m'   # white
BD = '\033[1m'    # bold
DM = '\033[2m'    # dim
RS = '\033[0m'    # reset

# ─── Lookup tables ────────────────────────────────────────────────────────────

BATTERY_TYPE = {0: 'User-defined', 1: 'Sealed', 2: 'GEL', 3: 'Flooded'}

CHARGING_STAGE = {0: 'Off', 1: 'Float', 2: 'Boost / Bulk', 3: 'Equalising'}

BATT_VOLTAGE_STATUS = {
    0: (G, 'Normal'),
    1: (R, 'Over-voltage'),
    2: (Y, 'Under-voltage'),
    3: (R, 'Low-voltage disconnect'),
    4: (R, 'Fault'),
}

# ─── Helpers ──────────────────────────────────────────────────────────────────

def word32(regs, lo, hi=None):
    """Combine two 16-bit registers into a 32-bit value (low word first)."""
    if hi is None:
        hi = lo + 1
    return regs[lo] | (regs[hi] << 16)

def signed(val):
    """Convert an unsigned 16-bit register to a signed integer."""
    return val if val < 0x8000 else val - 0x10000

def fmt_v(val):   return f"{G}{val:6.2f}{RS} V"
def fmt_a(val):   return f"{G}{val:6.2f}{RS} A"
def fmt_w(val):   return f"{G}{val:7.1f}{RS} W"
def fmt_kwh(val): return f"{G}{val:7.3f}{RS} kWh"
def fmt_c(val):   return f"{G}{val:5.1f}{RS} °C"
def fmt_ah(val):  return f"{G}{val:7.2f}{RS} Ah"
def fmt_pct(val): return f"{G}{val:3d}{RS} %"

def section(title):
    print(f"\n  {BD}{B}{title}{RS}")
    print(f"  {'─' * 56}")

def row(label, value, note=''):
    note_str = f"  {DM}{note}{RS}" if note else ''
    print(f"  {C}{label:<34}{RS}{value}{note_str}")

def decode_batt_status(reg):
    volt_code = reg & 0x0F
    color, label = BATT_VOLTAGE_STATUS.get(volt_code, (Y, f'Unknown ({volt_code})'))
    parts = [f"{color}{label}{RS}"]
    if reg & 0x10: parts.append(f"{R}Temp too high{RS}")
    if reg & 0x20: parts.append(f"{Y}Temp too low{RS}")
    if reg & 0x40: parts.append(f"{Y}Wrong rated-voltage ID{RS}")
    return '  '.join(parts)

def decode_chg_status(reg):
    stage_bits = (reg >> 2) & 0x03
    stage = CHARGING_STAGE.get(stage_bits, f'Unknown ({stage_bits})')

    inp_volt_status = (reg >> 14) & 0x03
    color = G if stage_bits != 0 or inp_volt_status == 0 else DM
    line = f"{color}{BD}{stage}{RS}"

    faults = []
    if inp_volt_status == 2: faults.append('Input over-voltage')
    if inp_volt_status == 3: faults.append('Input voltage error')
    if reg & (1 << 13): faults.append('Anti-reverse MOSFET short')
    if reg & (1 << 12): faults.append('Charging MOSFET short')
    if reg & (1 << 11): faults.append('Charging or anti-reverse MOSFET open')
    if reg & (1 << 10): faults.append('Input over-current')
    if reg & (1 <<  9): faults.append('Load over-current')
    if reg & (1 <<  8): faults.append('Load short')
    if reg & (1 <<  7): faults.append('Load MOSFET short')
    if reg & (1 <<  6): faults.append('PV input short')
    if reg & (1 <<  4): faults.append('PV input over-power')
    if reg & (1 <<  1): faults.append('Disequilibrium in three circuits')
    if reg & (1 <<  0): faults.append('PV shorted in night')

    if faults:
        line += f"  {R}⚠ " + ', '.join(faults) + RS
    return line

def clear_screen():
    sys.stdout.write('\033[2J\033[H')
    sys.stdout.flush()

# ─── Main loop ────────────────────────────────────────────────────────────────

def main():
    instrument = minimalmodbus.Instrument(PORT, SLAVE)
    instrument.serial.baudrate = 115200
    instrument.serial.bytesize = 8
    instrument.serial.parity   = 'N'
    instrument.serial.stopbits = 1
    instrument.serial.timeout  = 1
    instrument.mode = minimalmodbus.MODE_RTU
    instrument.debug = False

    signal.signal(signal.SIGINT, lambda *_: (print(f"\n{RS}Bye.\n"), sys.exit(0)))

    errors = 0
    while True:
        try:
            # ── Read all register blocks ─────────────────────────────────────
            # 0x3100–0x3117 : real-time PV / battery / load / temperatures
            rt   = instrument.read_registers(0x3100, 24, 4)
            # 0x3200–0x3202 : status flags + load relay
            st   = instrument.read_registers(0x3200, 3, 4)
            # 0x3300–0x3313 : today's and historical statistics
            hist = instrument.read_registers(0x3300, 20, 4)
            # 0x311A        : battery state-of-charge (%)
            soc_reg = instrument.read_registers(0x311A, 1, 4)
            # 0x9000–0x900E : battery & charging parameters (holding regs)
            params = instrument.read_registers(0x9000, 15, 3)
            # 0x9013–0x9015 : equalize / boost / float duration (minutes)
            timings = instrument.read_registers(0x9013, 3, 3)

            errors = 0

        except Exception as exc:
            errors += 1
            clear_screen()
            print(f"\n  {R}{BD}Read error (attempt {errors}): {exc}{RS}")
            print(f"  {DM}Retrying in 3 s…{RS}\n")
            time.sleep(3)
            continue

        # ── Parse real-time values ───────────────────────────────────────────
        pv_v   = rt[0] / 100
        pv_a   = rt[1] / 100
        pv_w   = word32(rt, 2, 3) / 100

        batt_v = rt[4] / 100
        batt_a = rt[5] / 100
        batt_w = word32(rt, 6, 7) / 100

        load_v = rt[8] / 100
        load_a = rt[9] / 100
        load_w = word32(rt, 10, 11) / 100

        # Temperatures — 0x310C = battery, 0x310D = ambient, 0x310E = heatsink
        batt_temp     = signed(rt[12]) / 100
        ambient_temp  = signed(rt[13]) / 100
        heatsink_temp = signed(rt[14]) / 100

        # Some models expose battery temp also at offset 16 (0x3110)
        batt_temp_alt = signed(rt[16]) / 100 if len(rt) > 16 else None

        soc = soc_reg[0]

        # ── Parse status ────────────────────────────────────────────────────
        batt_status = st[0]
        chg_status  = st[1]
        load_state  = st[2]

        chg_stage_bits = (chg_status >> 2) & 0x03

        # ── Parse today's statistics ────────────────────────────────────────
        today_max_pv_v    = hist[0] / 100
        today_min_pv_v    = hist[1] / 100
        today_max_batt_v  = hist[2] / 100
        today_min_batt_v  = hist[3] / 100
        today_max_chg_a   = hist[4] / 100
        today_max_dchg_a  = hist[5] / 100
        today_max_chg_w   = word32(hist, 6, 7) / 100
        today_max_dchg_w  = word32(hist, 8, 9) / 100
        today_chg_ah      = word32(hist, 10, 11) / 100
        today_kwh         = word32(hist, 12, 13) / 100
        month_kwh         = word32(hist, 14, 15) / 100
        year_kwh          = word32(hist, 16, 17) / 100
        total_kwh         = word32(hist, 18, 19) / 100

        # ── Parse parameters ────────────────────────────────────────────────
        batt_type    = BATTERY_TYPE.get(params[0], f'Unknown ({params[0]})')
        batt_cap_ah  = params[1]
        temp_comp    = params[2]          # mV/°C/2V, divide by 100 for V
        ov_disc_v    = params[3]  / 100   # over-voltage disconnect
        chg_limit_v  = params[4]  / 100   # charging limit
        ov_recon_v   = params[5]  / 100   # over-voltage reconnect
        equalize_v   = params[6]  / 100
        boost_v      = params[7]  / 100
        float_v      = params[8]  / 100
        boost_recon_v = params[9] / 100
        lv_recon_v   = params[10] / 100   # low-voltage reconnect
        uv_warn_rv   = params[11] / 100   # under-voltage warning recover
        uv_warn_v    = params[12] / 100   # under-voltage warning
        lv_disc_v    = params[13] / 100   # low-voltage disconnect
        dchg_limit_v = params[14] / 100   # discharging limit

        equalize_dur = timings[0]         # minutes
        boost_dur    = timings[1]         # minutes
        float_dur    = timings[2]         # minutes

        # ── Draw ─────────────────────────────────────────────────────────────
        clear_screen()
        now = time.strftime('%Y-%m-%d %H:%M:%S')
        print(f"\n  {BD}{W}EPEVER Tracer — Live Monitor{RS}   "
              f"{DM}{PORT}  slave={SLAVE}  {now}{RS}")
        print(f"  {'═' * 56}")

        # PV Array
        section('PV Array  (input)')
        row('Voltage',  fmt_v(pv_v))
        row('Current',  fmt_a(pv_a))
        row('Power',    fmt_w(pv_w))

        # Battery
        section('Battery')
        row('Voltage',          fmt_v(batt_v))
        row('Charging current', fmt_a(batt_a))
        row('Charging power',   fmt_w(batt_w))
        row('State of charge',  fmt_pct(soc),
            'register 0x311A — may read 0 if unsupported')
        row('Temperature (0x310C)', fmt_c(batt_temp),
            'battery sensor')
        if batt_temp_alt is not None and batt_temp_alt != batt_temp:
            row('Temperature (0x3110)', fmt_c(batt_temp_alt),
                'alt register — used by some models')
        row('Status',           decode_batt_status(batt_status),
            f'raw 0x{batt_status:04X}')

        # Charging state
        section('Charging State')
        row('Stage',    decode_chg_status(chg_status),
            f'raw 0x{chg_status:04X}')
        row('Stage bits [3:2]',
            f"{G}{BD}{CHARGING_STAGE.get(chg_stage_bits, '?')}{RS}",
            f'bits = {chg_stage_bits:02b}')

        # Controller temperatures
        section('Controller Temperatures')
        row('Ambient  (0x310D)', fmt_c(ambient_temp))
        row('Heatsink (0x310E)', fmt_c(heatsink_temp))

        # Load
        section('Load Output')
        row('Voltage', fmt_v(load_v))
        row('Current', fmt_a(load_a))
        row('Power',   fmt_w(load_w))
        row('Relay',   f"{G}On{RS}" if load_state else f"{DM}Off{RS}")

        # Today's statistics
        section("Today's Statistics  (regs 0x3300–0x330D)")
        row('Generated energy', fmt_kwh(today_kwh))
        row('Charging amp-hours', fmt_ah(today_chg_ah))
        row('Max PV voltage',   fmt_v(today_max_pv_v))
        row('Min PV voltage',   fmt_v(today_min_pv_v))
        row('Max battery voltage', fmt_v(today_max_batt_v))
        row('Min battery voltage', fmt_v(today_min_batt_v))
        row('Max charging current', fmt_a(today_max_chg_a))
        row('Max charging power',   fmt_w(today_max_chg_w))
        row('Max discharge power',  fmt_w(today_max_dchg_w))

        # Cumulative energy
        section('Cumulative Energy')
        row('This month', fmt_kwh(month_kwh))
        row('This year',  fmt_kwh(year_kwh))
        row('All time',   fmt_kwh(total_kwh))

        # Charging parameters
        section('Charging Parameters  (holding regs 0x9000+)')
        row('Battery type',           f"{W}{batt_type}{RS}")
        row('Battery capacity',       f"{W}{batt_cap_ah}{RS} Ah")
        row('Over-voltage disconnect', fmt_v(ov_disc_v))
        row('Charging limit voltage',  fmt_v(chg_limit_v))
        row('Equalize voltage',        fmt_v(equalize_v))
        row('Boost voltage',           fmt_v(boost_v))
        row('Float voltage',           fmt_v(float_v))
        row('Boost reconnect voltage', fmt_v(boost_recon_v))
        row('Low-voltage reconnect',   fmt_v(lv_recon_v))
        row('Under-voltage warning',   fmt_v(uv_warn_v))
        row('Low-voltage disconnect',  fmt_v(lv_disc_v))
        row('Temp compensation',       f"{W}{temp_comp}{RS} mV/°C/2V")

        # Timing parameters
        section('Phase Durations  (holding regs 0x9013+)')
        row('Equalize duration', f"{W}{equalize_dur}{RS} min")
        row('Boost duration',    f"{W}{boost_dur}{RS} min")
        row('Float duration',    f"{W}{float_dur}{RS} min")

        print(f"\n  {DM}Ctrl+C to exit • refreshes every {INTERVAL:.0f} s{RS}\n")
        time.sleep(INTERVAL)

if __name__ == '__main__':
    main()
