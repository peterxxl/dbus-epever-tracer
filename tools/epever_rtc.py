"""
EPEVER Tracer — RTC register helpers

Shared by the driver (automatic clock sync on startup) and the
epever-update-clock.py tool (interactive clock sync).

Registers 0x9013–0x9015 (FC03 read / FC10 write):
  0x9013  high byte = minute,  low byte = second
  0x9014  high byte = day,     low byte = hour
  0x9015  high byte = year (2-digit, offset from 2000), low byte = month
"""

from datetime import datetime


def read_clock(ctrl):
    """Return the controller RTC as a naive local datetime, or None on failure."""
    try:
        regs = ctrl.read_registers(0x9013, 3, 3)
        sec  =  regs[0] & 0xFF
        mn   = (regs[0] >> 8) & 0xFF
        hr   =  regs[1] & 0xFF
        day  = (regs[1] >> 8) & 0xFF
        mon  =  regs[2] & 0xFF
        yr   = (regs[2] >> 8) & 0xFF
        return datetime(2000 + yr, mon, day, hr, mn, sec)
    except Exception:
        return None


def write_clock(ctrl, dt):
    """Write dt to the controller RTC (registers 0x9013–0x9015, FC10)."""
    reg0 = ((dt.minute & 0xFF) << 8) | (dt.second & 0xFF)
    reg1 = ((dt.day    & 0xFF) << 8) | (dt.hour   & 0xFF)
    reg2 = ((dt.year % 100   ) << 8) | (dt.month  & 0xFF)
    ctrl.write_registers(0x9013, [reg0, reg1, reg2])
