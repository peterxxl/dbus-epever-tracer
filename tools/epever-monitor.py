#!/usr/bin/env python3
"""
EPEVER Tracer — Live Monitor

Reads every available Modbus register block and displays them in a
colour-coded real-time terminal UI. Useful for debugging and discovering
values to implement in the driver.

Usage:
  python3 epever-monitor.py [port] [slave_addr] [interval_sec] [--dump] [--manual]

Examples:
  python3 epever-monitor.py
  python3 epever-monitor.py /dev/ttyUSB0
  python3 epever-monitor.py /dev/ttyUSB0 1 2
  python3 epever-monitor.py /dev/ttyUSB0 1 2 --dump     # raw dump to file + exit
  python3 epever-monitor.py /dev/ttyUSB0 1 2 --manual   # press Enter to refresh
"""

import sys
import os
import time
import signal
from datetime import datetime, timezone

_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(_DIR, '../ext'))
sys.path.insert(0, _DIR)  # tools/ — for epever_rtc

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
from epever_rtc import read_clock

# ─── CLI args ─────────────────────────────────────────────────────────────────

args     = [a for a in sys.argv[1:] if not a.startswith('--')]
flags    = {a for a in sys.argv[1:] if a.startswith('--')}
PORT     = args[0] if len(args) > 0 else '/dev/ttyUSB0'
SLAVE    = int(args[1]) if len(args) > 1 else 1
INTERVAL = float(args[2]) if len(args) > 2 else 2.0
DUMP     = '--dump' in flags
MANUAL   = '--manual' in flags


# ─── Tee: write to multiple streams at once ───────────────────────────────────

class _Tee:
    def __init__(self, *streams):
        self.streams = streams
    def write(self, data):
        for s in self.streams:
            s.write(data)
    def flush(self):
        for s in self.streams:
            s.flush()

# ─── ANSI colours ─────────────────────────────────────────────────────────────

R  = '\033[91m'
G  = '\033[92m'
Y  = '\033[93m'
B  = '\033[94m'
C  = '\033[96m'
W  = '\033[97m'
BD = '\033[1m'
DM = '\033[2m'
RS = '\033[0m'

# ─── Lookup tables ────────────────────────────────────────────────────────────

BATTERY_TYPE = {0: 'User-defined', 1: 'Sealed', 2: 'GEL', 3: 'Flooded'}
CHARGING_STAGE = {0: 'Off / No charging', 1: 'Float', 2: 'Boost / Bulk', 3: 'Equalising'}
LOAD_CONTROL_MODE = {0: 'Manual', 1: 'Light ON/OFF', 2: 'Light ON + Timer', 3: 'Time Control'}
BATT_MGMT_MODE = {0: 'Voltage compensation', 1: 'SOC'}
CHARGING_MODE = {1: 'PWM', 2: 'MPPT'}

BATT_VOLTAGE_STATUS = {
    0: (G, 'Normal'), 1: (R, 'Over-voltage'), 2: (Y, 'Under-voltage'),
    3: (R, 'Low Voltage Disconnect'), 4: (R, 'Fault'),
}

# ─── Helpers ──────────────────────────────────────────────────────────────────

def word32(regs, lo, hi=None):
    if hi is None:
        hi = lo + 1
    return regs[lo] | (regs[hi] << 16)

def signed16(val):
    return val if val < 0x8000 else val - 0x10000

def v(val):   return f"{G}{val:6.2f}{RS} V"
def a(val):   return f"{G}{val:6.2f}{RS} A"
def w(val):   return f"{G}{val:7.1f}{RS} W"
def kwh(val): return f"{G}{val:8.3f}{RS} kWh"
def c(val):   return f"{G}{val:5.1f}{RS} °C"
def ah(val):  return f"{G}{val:7.2f}{RS} Ah"
def pct(val): return f"{G}{val:3d}{RS} %"
def na():     return f"{DM}N/A{RS}"

def section(title):
    print(f"\n  {BD}{B}{title}{RS}")
    print(f"  {'─' * 58}")

def row(label, value, note=''):
    note_str = f"  {DM}{note}{RS}" if note else ''
    print(f"  {C}{label:<36}{RS}{value}{note_str}")

def decode_batt_status(reg):
    volt_code = reg & 0x0F
    color, label = BATT_VOLTAGE_STATUS.get(volt_code, (Y, f'Unknown ({volt_code})'))
    parts = [f"{color}{label}{RS}"]
    if reg & 0x10: parts.append(f"{R}Temp too high{RS}")
    if reg & 0x20: parts.append(f"{Y}Temp too low{RS}")
    if reg & 0x100: parts.append(f"{Y}Internal resistance abnormal{RS}")
    if reg & 0x8000: parts.append(f"{R}Wrong rated voltage{RS}")
    return '  '.join(parts) if parts else f"{G}Normal{RS}"

def decode_chg_status(reg):
    stage_bits = (reg >> 2) & 0x03
    stage = CHARGING_STAGE.get(stage_bits, f'Unknown ({stage_bits})')
    inp_status = (reg >> 14) & 0x03

    color = G if stage_bits > 0 else DM
    line = f"{color}{BD}{stage}{RS}"

    faults = []
    if inp_status == 1: faults.append('No PV power')
    if inp_status == 2: faults.append('PV over-voltage')
    if inp_status == 3: faults.append('PV voltage error')
    if reg & (1 << 13): faults.append('Charging MOSFET short')
    if reg & (1 << 12): faults.append('Charging/anti-reverse MOSFET short')
    if reg & (1 << 11): faults.append('Anti-reverse MOSFET short')
    if reg & (1 << 10): faults.append('Input over-current')
    if reg & (1 <<  9): faults.append('Load over-current')
    if reg & (1 <<  8): faults.append('Load short')
    if reg & (1 <<  7): faults.append('Load MOSFET short')
    if reg & (1 <<  4): faults.append('PV input short')
    if reg & (1 <<  1): faults.append('Fault')
    running = bool(reg & 1)

    if faults:
        line += f"  {R}⚠ " + ', '.join(faults) + RS
    line += f"  {'Running' if running else f'{DM}Standby{RS}'}"
    return line

def clear_screen():
    sys.stdout.write('\033[2J\033[H')
    sys.stdout.flush()

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    instr = minimalmodbus.Instrument(PORT, SLAVE)
    instr.serial.baudrate = 115200
    instr.serial.bytesize = 8
    instr.serial.parity   = 'N'
    instr.serial.stopbits = 1
    instr.serial.timeout  = 0.5   # 200 ms is too tight for the 45-byte stats block
    instr.mode = minimalmodbus.MODE_RTU
    instr.debug = False

    dump_file = None
    if DUMP:
        dump_filename = f"epever-dump-{time.strftime('%Y%m%d-%H%M%S')}.txt"
        dump_file = open(dump_filename, 'w')
        sys.stdout = _Tee(sys.__stdout__, dump_file)
        instr.debug = True
        print(f"# EPEVER Tracer raw dump — {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"# Port: {PORT}  Slave: {SLAVE}")
        print()

    signal.signal(signal.SIGINT, lambda *_: (print(f"\n{RS}Bye.\n"), sys.exit(0)))

    # Warn if the EPEVER driver is already polling the same port.
    # Both processes share the serial bus; whichever reads first takes the
    # controller's response, leaving the other with garbage or nothing.
    import subprocess
    try:
        out = subprocess.check_output(['pgrep', '-a', '-f', 'dbus-epever-tracer'],
                                      stderr=subprocess.DEVNULL).decode()
        tty = PORT.split('/')[-1]
        if 'dbus-epever-tracer.py' in out:
            print(f"\n  {Y}{BD}Warning:{RS} {Y}the EPEVER driver is running and polling {PORT}.{RS}")
            print(f"  {Y}Intermittent checksum errors are expected until you stop it:{RS}")
            print(f"  {W}  svc -d /service/dbus-epever-tracer.{tty}{RS}\n")
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass  # pgrep not found or no match — fine

    errors = 0
    while True:
        instr.serial.reset_input_buffer()   # clear any stale bytes from previous iteration
        read_errors = {}

        def safe_read(addr, count, fc, label=''):
            try:
                instr.serial.reset_input_buffer()
                result = instr.read_registers(addr, count, fc)
                time.sleep(0.05)
                return result
            except Exception as exc:
                instr.serial.reset_input_buffer()
                time.sleep(0.15)
                key = label or f'0x{addr:04X}'
                read_errors[key] = str(exc)
                return None

        def safe_bit(addr, fc, label=''):
            try:
                instr.serial.reset_input_buffer()
                result = instr.read_bit(addr, fc)
                time.sleep(0.05)
                return result
            except Exception as exc:
                instr.serial.reset_input_buffer()
                time.sleep(0.15)
                key = label or f'0x{addr:04X}'
                read_errors[key] = str(exc)
                return None

        # ── Real-time data (FC04, 0x3100–0x3111 = 18 regs) ──────────────────
        # Count confirmed by the working driver; 24 causes immediate exception 02.
        rt      = safe_read(0x3100, 18, 4, 'real-time (0x3100)')
        # ── Extended real-time: SOC, remote temp, system voltage (FC04) ──────
        # 0x311A returns Modbus exception 02 (Illegal Data Address) on Tracer-AN;
        # read one register at a time so a single unsupported address doesn't
        # corrupt the entire block.
        rt_ext_soc  = safe_read(0x311A, 1, 4, 'soc (0x311A)')
        rt_ext_rtemp = safe_read(0x311B, 1, 4, 'remote-temp (0x311B)')
        rt_ext_sysvolt = safe_read(0x311D, 1, 4, 'sys-volt (0x311D)')
        # ── Status (FC04) ─────────────────────────────────────────────────────
        st      = safe_read(0x3200, 3, 4, 'status (0x3200)')
        # ── Statistics (FC04, 0x3300–0x3313 = 20 regs) ──────────────────────
        # Dump confirmed the controller sends exactly 20 regs; 32 causes exception 02.
        hist    = safe_read(0x3300, 20, 4, 'statistics (0x3300)')
        # ── Charging parameters (FC03, holding registers) ─────────────────────
        params  = safe_read(0x9000, 15, 3, 'params (0x9000)')  # 0x9000–0x900E
        params2 = safe_read(0x9016, 12, 3, 'params2 (0x9016)') # 0x9016–0x9021 (temp limits, night/day V)
        clock   = read_clock(instr)   # 0x9013–0x9015 real-time clock
        load_ctrl = safe_read(0x903D, 1, 3, 'load-ctrl (0x903D)') # 0x903D load control mode
        phase_dur = safe_read(0x906B, 6, 3, 'phase-dur (0x906B)') # 0x906B–0x9070
        # ── Discrete inputs (FC02) ────────────────────────────────────────────
        dis_ot  = safe_bit(0x2000, 2, 'over-temp (0x2000)')   # over-temperature
        dis_dn  = safe_bit(0x200C, 2, 'day-night (0x200C)')   # day/night

        if rt is None or st is None or hist is None:
            errors += 1
            if not DUMP:
                clear_screen()
            print(f"\n  {R}{BD}Cannot read core registers (attempt {errors}){RS}")
            for label, msg in read_errors.items():
                print(f"  {Y}  {label}:{RS} {msg}")
            print(f"\n  {DM}Retrying in 3 s…{RS}\n")
            time.sleep(3)
            continue
        errors = 0

        # ── Parse real-time (0x3100–0x3111, indices 0–17) ────────────────────
        pv_v   = rt[0] / 100
        pv_a   = rt[1] / 100
        pv_w   = word32(rt, 2, 3) / 100
        batt_v = rt[4] / 100
        batt_a = rt[5] / 100
        batt_w = word32(rt, 6, 7) / 100

        # 0x310C–0x310F: load output (v2.5 spec; 0x3108–0x310B undocumented/unused)
        load_v = rt[12] / 100        # 0x310C load voltage
        load_a = rt[13] / 100        # 0x310D load current (driver-confirmed)
        load_w = word32(rt, 14, 15) / 100  # 0x310E–0x310F load power
        # 0x3110–0x3111: temperature registers
        batt_temp_3110 = signed16(rt[16]) / 100
        ctrl_temp_3111 = signed16(rt[17]) / 100

        # ── Parse extended real-time ──────────────────────────────────────────
        soc         = rt_ext_soc[0]              if rt_ext_soc    else None  # 0x311A
        remote_temp = signed16(rt_ext_rtemp[0]) / 100 if rt_ext_rtemp else None  # 0x311B
        sys_volt    = rt_ext_sysvolt[0] / 100    if rt_ext_sysvolt else None  # 0x311D

        # ── Parse status ──────────────────────────────────────────────────────
        batt_status = st[0]
        chg_status  = st[1]
        load_state  = st[2]
        chg_stage   = (chg_status >> 2) & 0x03

        # ── Parse statistics (0x3300–0x3313, indices 0–19) ───────────────────
        today_max_pv_v   = hist[0] / 100
        today_min_pv_v   = hist[1] / 100
        today_max_batt_v = hist[2] / 100
        today_min_batt_v = hist[3] / 100
        consumed_today   = word32(hist, 4,  5)  / 100  # 0x3304–0x3305
        consumed_month   = word32(hist, 6,  7)  / 100  # 0x3306–0x3307
        consumed_year    = word32(hist, 8,  9)  / 100  # 0x3308–0x3309
        consumed_total   = word32(hist, 10, 11) / 100  # 0x330A–0x330B
        generated_today  = word32(hist, 12, 13) / 100  # 0x330C–0x330D
        generated_month  = word32(hist, 14, 15) / 100  # 0x330E–0x330F
        generated_year   = word32(hist, 16, 17) / 100  # 0x3310–0x3311
        generated_total  = word32(hist, 18, 19) / 100  # 0x3312–0x3313
        # 0x3314+ not available (controller only returns 20 registers)

        # ── Parse charging parameters ─────────────────────────────────────────
        if params:
            batt_type     = BATTERY_TYPE.get(params[0], f'Unknown ({params[0]})')
            batt_cap_ah   = params[1]
            temp_comp     = params[2]
            ov_disc_v     = params[3]  / 100
            chg_limit_v   = params[4]  / 100
            ov_recon_v    = params[5]  / 100
            equalize_v    = params[6]  / 100
            boost_v       = params[7]  / 100
            float_v       = params[8]  / 100
            boost_recon_v = params[9]  / 100
            lv_recon_v    = params[10] / 100
            uv_warn_rv    = params[11] / 100
            uv_warn_v     = params[12] / 100
            lv_disc_v     = params[13] / 100
            dchg_limit_v  = params[14] / 100
        else:
            (batt_type, batt_cap_ah, temp_comp, ov_disc_v, chg_limit_v, ov_recon_v,
             equalize_v, boost_v, float_v, boost_recon_v, lv_recon_v,
             uv_warn_rv, uv_warn_v, lv_disc_v, dchg_limit_v) = [None] * 15

        if params2:
            eq_cycle    = params2[0]           # 0x9016 days
            batt_t_high = params2[1] / 100     # 0x9017
            batt_t_low  = signed16(params2[2]) / 100  # 0x9018 (signed: can be negative)
            ctrl_t_high = params2[3] / 100     # 0x9019
            ctrl_t_rec  = params2[4] / 100     # 0x901A
            pwr_t_high  = params2[5] / 100     # 0x901B
            pwr_t_rec   = params2[6] / 100     # 0x901C
            line_imp    = params2[7] / 100      # 0x901D mΩ
            night_v     = params2[8] / 100      # 0x901E
            night_delay = params2[9]            # 0x901F minutes
            day_v       = params2[10] / 100     # 0x9020
            day_delay   = params2[11]           # 0x9021 minutes
        else:
            (eq_cycle, batt_t_high, batt_t_low, ctrl_t_high, ctrl_t_rec,
             pwr_t_high, pwr_t_rec, line_imp, night_v, night_delay,
             day_v, day_delay) = [None] * 12

        clock_str = clock.strftime('%Y-%m-%d %H:%M:%S') if clock else None

        load_mode   = LOAD_CONTROL_MODE.get(load_ctrl[0], f'Unknown') if load_ctrl else None
        if phase_dur:
            eq_dur   = phase_dur[0]   # 0x906B equalize minutes
            boost_dur = phase_dur[1]  # 0x906C boost minutes
            dchg_pct = phase_dur[3] / 100 if len(phase_dur) > 3 else None  # 0x906D
            chg_pct  = phase_dur[4] / 100 if len(phase_dur) > 4 else None  # 0x906E
            mgmt_mode = BATT_MGMT_MODE.get(phase_dur[5], 'Unknown') if len(phase_dur) > 5 else None  # 0x9070
        else:
            eq_dur = boost_dur = dchg_pct = chg_pct = mgmt_mode = None

        # ── Draw ─────────────────────────────────────────────────────────────
        if not DUMP:
            clear_screen()
        # Use timezone-aware local time so the comparison is correct even
        # when the TZ environment variable is not set (common on Venus OS).
        now_local = datetime.now(timezone.utc).astimezone()
        now_str   = now_local.strftime('%Y-%m-%d %H:%M:%S')
        tz_name   = now_local.strftime('%Z')
        print(f"\n  {BD}{W}EPEVER Tracer — Live Monitor{RS}   "
              f"{DM}{PORT}  slave={SLAVE}  {tz_name}{RS}")
        print(f"  {'═' * 58}")
        if clock_str:
            try:
                drift     = int((now_local.replace(tzinfo=None) - clock).total_seconds())
                drift_abs = abs(drift)
                sign      = '+' if drift >= 0 else '-'
                dc        = G if drift_abs < 60 else (Y if drift_abs < 300 else R)
                drift_tag = f"{dc}{sign}{drift_abs} s{RS}"
            except Exception:
                drift_tag = f"{DM}?{RS}"
            print(f"  {DM}Controller : {RS}{clock_str}")
            print(f"  {DM}System     : {RS}{now_str}   [{drift_tag}{DM}]{RS}")
        else:
            print(f"  {DM}System     : {now_str}  {tz_name}{RS}")
        print(f"  {'═' * 58}")

        # PV array
        section('PV Array  (0x3100–0x3103)')
        row('Voltage',  v(pv_v),  '0x3100')
        row('Current',  a(pv_a),  '0x3101')
        row('Power',    w(pv_w),  '0x3102–0x3103')

        # Battery
        section('Battery  (0x3104–0x3107, 0x3110–0x3111)')
        row('Voltage',               v(batt_v),          '0x3104')
        row('Charging current',      a(batt_a),          '0x3105')
        row('Charging power',        w(batt_w),          '0x3106–0x3107')
        row('Temperature',           c(batt_temp_3110),  '0x3110')
        if remote_temp is not None:
            row('Remote temperature',     c(remote_temp),     '0x311B')
        if soc is not None and soc != 0:
            row('State of charge',        pct(soc),           '0x311A')
        else:
            row('State of charge',        na(),               '0x311A — not supported by this model')
        row('Status',                decode_batt_status(batt_status), f'0x3200  raw 0x{batt_status:04X}')

        # Charging state
        section('Charging State  (0x3201)')
        row('Stage',  decode_chg_status(chg_status), f'0x3201  raw 0x{chg_status:04X}')
        row('Stage bits [3:2]',
            f"{G}{BD}{CHARGING_STAGE.get(chg_stage, '?')}{RS}",
            f'bits={chg_stage:02b}')

        # Controller
        section('Controller  (0x3111)')
        row('Internal temp',           c(ctrl_temp_3111),              '0x3111')
        if dis_ot is not None:
            ot_str = f"{R}YES — over temperature!{RS}" if dis_ot else f"{G}Normal{RS}"
            row('Over-temperature flag',  ot_str,                      '0x2000')
        if dis_dn is not None:
            dn_str = f"{DM}Night{RS}" if dis_dn else f"{G}Day{RS}"
            row('Day / Night',            dn_str,                      '0x200C')
        if sys_volt is not None:
            row('System rated voltage',   f"{W}{sys_volt:.0f}{RS} V",  '0x311D')

        # Load
        section('Load Output  (0x310C–0x310F, 0x3202)')
        row('Relay state',  f"{G}On{RS}" if load_state else f"{DM}Off{RS}",  '0x3202')
        row('Voltage',      v(load_v),   '0x310C')
        row('Current',      a(load_a),   '0x310D')
        row('Power',        w(load_w),   '0x310E–0x310F')
        if load_mode is not None:
            row('Control mode',  f"{W}{load_mode}{RS}",  '0x903D')

        # Generated energy
        section('Generated Energy  (PV → battery, 0x330C–0x3313)')
        row('Today',      kwh(generated_today),   '0x330C–0x330D')
        row('This month', kwh(generated_month),   '0x330E–0x330F')
        row('This year',  kwh(generated_year),    '0x3310–0x3311')
        row('All time',   kwh(generated_total),   '0x3312–0x3313')

        # Consumed energy
        section('Consumed Energy  (load output, 0x3304+)')
        row('Today',      kwh(consumed_today),    '0x3304–0x3305')
        row('This month', kwh(consumed_month),    '0x3306–0x3307')
        row('This year',  kwh(consumed_year),     '0x3308–0x3309')
        row('All time',   kwh(consumed_total),    '0x330A–0x330B')

        # Today's records
        section("Today's Records  (0x3300–0x3303)")
        row('Max PV voltage',      v(today_max_pv_v),   '0x3300')
        row('Min PV voltage',      v(today_min_pv_v),   '0x3301')
        row('Max battery voltage', v(today_max_batt_v), '0x3302')
        row('Min battery voltage', v(today_min_batt_v), '0x3303')

        # Charging parameters
        section('Charging Parameters  (0x9000–0x900E)')
        row('Battery type',            f"{W}{batt_type}{RS}"          if batt_type     is not None else na(), '0x9000')
        row('Battery capacity',        f"{W}{batt_cap_ah}{RS} Ah"     if batt_cap_ah   is not None else na(), '0x9001')
        row('Battery management mode', f"{W}{mgmt_mode}{RS}"          if mgmt_mode     is not None else na(), '0x9070')
        row('High voltage disconnect', v(ov_disc_v)                   if ov_disc_v     is not None else na(), '0x9003')
        row('Charging limit voltage',  v(chg_limit_v)                 if chg_limit_v   is not None else na(), '0x9004')
        row('Equalize voltage',        v(equalize_v)                  if equalize_v    is not None else na(), '0x9006')
        row('Boost voltage',           v(boost_v)                     if boost_v       is not None else na(), '0x9007')
        row('Float voltage',           v(float_v)                     if float_v       is not None else na(), '0x9008')
        row('Boost reconnect voltage', v(boost_recon_v)               if boost_recon_v is not None else na(), '0x9009')
        row('Low voltage reconnect',   v(lv_recon_v)                  if lv_recon_v    is not None else na(), '0x900A')
        row('Under-voltage warning',   v(uv_warn_v)                   if uv_warn_v     is not None else na(), '0x900C')
        row('Low voltage disconnect',  v(lv_disc_v)                   if lv_disc_v     is not None else na(), '0x900D')
        row('Temp compensation',       f"{W}{temp_comp}{RS} mV/°C/2V" if temp_comp     is not None else na(), '0x9002')

        # Temperature protection thresholds
        if params2:
            section('Temperature Protection Thresholds  (0x9017+)')
            row('Battery temp high limit',    c(batt_t_high), '0x9017')
            row('Battery temp low limit',     c(batt_t_low),  '0x9018')
            row('Controller temp high limit', c(ctrl_t_high), '0x9019')
            row('Controller temp recovery',   c(ctrl_t_rec),  '0x901A')
            row('Heatsink temp high limit',   c(pwr_t_high),  '0x901B')
            row('Heatsink temp recovery',     c(pwr_t_rec),   '0x901C')

        # Night/day detection
        if params2:
            section('Night / Day Detection  (0x901E–0x9021)')
            row('Night threshold voltage',  v(night_v),          '0x901E — PV below this = night')
            row('Night detection delay',    f"{W}{night_delay}{RS} min", '0x901F')
            row('Day threshold voltage',    v(day_v),            '0x9020 — PV above this = day')
            row('Day detection delay',      f"{W}{day_delay}{RS} min",   '0x9021')

        # Phase durations
        section('Phase Durations  (0x906B–0x906C)')
        row('Equalize cycle', f"{W}{eq_cycle}{RS} days" if eq_cycle is not None else na(), '0x9016')
        row('Equalize duration', f"{W}{eq_dur}{RS} min" if eq_dur   is not None else na(), '0x906B')
        row('Boost duration',    f"{W}{boost_dur}{RS} min" if boost_dur is not None else na(), '0x906C')
        if dchg_pct is not None:
            row('Discharging stop %', f"{W}{dchg_pct:.0f}{RS} %", '0x906D')
        if chg_pct is not None:
            row('Charging depth %',   f"{W}{chg_pct:.0f}{RS} %", '0x906E')

        if DUMP:
            sys.stdout = sys.__stdout__
            dump_file.close()
            print(f"\nDump saved to: {dump_filename}")
            return

        if MANUAL:
            print(f"\n  {DM}Press Enter to refresh, Ctrl+C to exit{RS}\n")
            try:
                input()
            except EOFError:
                return
        else:
            print(f"\n  {DM}Ctrl+C to exit • refreshes every {INTERVAL:.0f} s{RS}\n")
            time.sleep(INTERVAL)

if __name__ == '__main__':
    main()
