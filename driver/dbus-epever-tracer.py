#!/usr/bin/env python3

# ------------------------------------------------------------------------------
# EPEVER Tracer DBus Service Driver for Venus OS
# ------------------------------------------------------------------------------
# This script provides a DBus service for integrating EPEVER Tracer solar charge
# controllers with Victron Energy's Venus OS. It communicates over Modbus RTU and
# exposes data in a format compatible with Victron's ecosystem (VRM, GX devices).
# ------------------------------------------------------------------------------

"""Driver for exposing EPEVER Tracer MPPT data on the system DBus.

This module implements the glue between an EPEVER Tracer solar charge controller
and Victron's DBus based ecosystem.  It communicates with the controller over
Modbus RTU and publishes the retrieved information using the same interface that
official Victron devices use.  Running this service on a Venus OS device allows
the Tracer controller to be monitored from VRM or any other Victron tool that
speaks DBus.

The code was written with simplicity in mind so only a single file is required
to run the service.  Where appropriate, comments reference the Victron DBus
paths that are being populated.

Features
--------
* Real-time monitoring of charger, battery and PV parameters.
* Historical statistics exported in the format expected by VRM.
* Automatic reconnection and basic error handling on serial failures.

Useful references when extending this driver are:
`Victron Energy DBus API <https://github.com/victronenergy/venus/wiki/dbus>`__
and the official EPEVER Tracer Modbus documentation.
"""


# ===============================
# Required libraries
# ===============================
import sys
import os

# Resolve symlinks so that relative paths work when the driver is run from
# /opt/victronenergy/dbus-epever-tracer/ (a symlink into /data/).
_DRIVER_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(1, os.path.join(_DRIVER_DIR, '../ext/velib_python'))
sys.path.insert(1, os.path.join(_DRIVER_DIR, '../ext'))  # bundled minimalmodbus

import minimalmodbus
import json
import logging
import traceback
import time
import datetime
from datetime import datetime, date, timedelta
from gi.repository import GLib  # For main event loop
import dbus
import dbus.service  # For DBus service implementation
import serial  # For serial port handling

# ===============================
# Local application imports
# ===============================
from vedbus import VeDbusService  # Victron's DBus service implementation

# Venus OS stores the timezone in DBus, not in /etc/localtime, so Python sees
# UTC unless we set TZ explicitly before any datetime calls.
def _apply_venus_timezone():
    if os.environ.get('TZ'):
        return
    try:
        obj = dbus.SystemBus().get_object(
            'com.victronenergy.settings', '/Settings/System/TimeZone')
        tz = str(obj.GetValue())
        if tz:
            os.environ['TZ'] = tz
            time.tzset()
    except Exception:
        pass

# _apply_venus_timezone() is called in main() after DBusGMainLoop(set_as_default=True),
# because dbus.SystemBus() caches the shared connection — calling it before the main loop
# is registered produces a connection without a main loop, which then breaks VeDbusService.

# ===============================
# Global configuration variables
# ===============================
# These variables define the driver version, device identity, and service settings.
serialnumber = 'WO20160415-008-0056'
productname = 'PV Charger'
firmwareversion = 'v2026.04.30-1353'
connection = 'USB'
servicename = 'com.victronenergy.solarcharger.tty'
tempservicename = 'com.victronenergy.temperature.tty'
switchservicename = 'com.victronenergy.switch.tty'
deviceinstance = 278             # VRM instance — solarcharger service
temperature_deviceinstance = 279 # VRM instance — temperature service
# State mapping for EPEVER to Victron charger states:
# Indexes: [00 01 10 11] where bits are [discharge, charge]
# 00 = No charging, 01 = Float, 10 = Boost, 11 = Equalizing
# Maps to Victron states: 0=Off, 5=Float, 3=Bulk, 6=Storage
state = [0,5,3,6]

# Mapping of common EPEVER fault bits to Victron MPPT error codes.  Only
# a subset of the Victron codes is used as the EPEVER protocol exposes
# fewer fault conditions.  Unknown or unset bits map to 0 (no error).
#
# Battery status register 0x3200 bits:
#  D3-D0  0x01 over-voltage, 0x02 under-voltage, 0x03 low-voltage disconnect,
#         0x04 fault
#  D5-D4  0x10 over-temperature, 0x20 low-temperature
#
# Charger status register 0x3201 bits:
#  D15-D14 input voltage status (2 = over-voltage, 3 = error)
#  D13..D7 various MOSFET and short-circuit faults
#  D10 input over-current
#  D4  PV shorted
# Victron MPPT error codes relevant for mapping EPEVER faults.  The values
# come from the Victron documentation.  Only a subset is currently used:
#   0  = No error
#   1  = Battery temperature too high
#   2  = Battery voltage too high
#   17 = Charger temperature too high
#   18 = Charger over-current
#   19 = Charger current polarity reversed (used for PV short)
#   34 = Input current too high
ERROR_MAP = {
    'no_error': 0,
    'battery_temp_high': 1,
    'battery_voltage_high': 2,
    'charger_temp_high': 17,
    'charger_over_current': 18,
    'charger_current_reversed': 19,
    'input_current_high': 34,
}

def map_epever_error(batt_status, chg_status):
    """Translate EPEVER status bits to a Victron MPPT error code."""
    # Battery related errors first
    batt_state = batt_status & 0x000F
    if batt_state == 0x01:
        return ERROR_MAP['battery_voltage_high']

    # Battery temperature flags
    if batt_status & 0x10:
        return ERROR_MAP['battery_temp_high']

    # Input voltage errors
    inp_status = (chg_status >> 14) & 0x03
    if inp_status == 3:
        return ERROR_MAP['input_current_high']

    # MOSFET and short circuit faults
    if chg_status & (1 << 13):
        return ERROR_MAP['charger_over_current']
    if chg_status & (1 << 12):
        return ERROR_MAP['charger_over_current']
    if chg_status & (1 << 11):
        return ERROR_MAP['charger_over_current']
    if chg_status & (1 << 10):
        return ERROR_MAP['input_current_high']
    if chg_status & (1 << 8):
        return ERROR_MAP['charger_over_current']
    if chg_status & (1 << 7):
        return ERROR_MAP['charger_temp_high']
    if chg_status & (1 << 4):
        return ERROR_MAP['charger_current_reversed']

    # No error conditions detected
    return 0

# Victron warning codes used below:
#   6  = Battery low temperature
#   20 = Low state of charge (used for under-voltage / low-voltage disconnect)
WARNING_MAP = {
    'low_soc': 20,
    'low_temperature': 6,
}

def map_epever_warning(batt_status):
    """Translate EPEVER battery status bits to a Victron MPPT warning code.

    Only warning-level conditions are mapped here; hard faults are handled
    by map_epever_error(). Register 0x3200 bits checked:
      D1 (0x02) — battery under-voltage
      D2 (0x04) — battery low-voltage disconnect
      D5 (0x20) — battery low temperature
    """
    if batt_status & 0x02:  # under-voltage
        return WARNING_MAP['low_soc']
    if batt_status & 0x04:  # low-voltage disconnect
        return WARNING_MAP['low_soc']
    if batt_status & 0x20:  # low temperature
        return WARNING_MAP['low_temperature']
    return 0

def _get_bit(num, i):
    """Return True if bit i of integer num is set."""
    return bool(num & (1 << i))

# Modbus register addresses (constants — safe at module level)
REGISTER_PV_BATTERY = 0x3100  # PV array voltage, current, power, etc.
REGISTER_CHARGER_STATE = 0x3200  # Charging status, charging stage, etc.
REGISTER_HISTORY = 0x3300  # Historical generated energy data
REGISTER_HISTORY_DAILY = 0x330C  # Daily historical generated energy data
REGISTER_PARAMETERS = 0x9000  # Charging and load parameters
REGISTER_CHARGE_VOLTAGES = 0x9007  # Boost (absorption) voltage setpoint; 0x9008 = float; 0x9009 = boost reconnect
REGISTER_BOOST_DURATION  = 0x906C  # Boost duration in minutes (holding register)
REGISTER_OVER_TEMP       = 0x2000  # Discrete input: controller over-temperature (FC02, 1=above protection threshold)

# controller and servicename are initialised in main() once the serial port
# is known and validated; declared here so the module-level scope is explicit.
controller = None

# ===============================
# Main DBus Service Class
# ===============================

class DbusEpever(object):
    def __init__(self):
        """Create and register the DBus service."""
        self._dbusservice = VeDbusService(servicename)
        self._exception_counter = 0
        self._load_command = None   # pending load on/off command from switch service

        # Variables for tracking charge state times
        self._last_update_time = time.time()
        self._current_charge_state = 0  # 0=Off, 3=Bulk, 4=Absorption, 5=Float, 7=Equalize
        self._time_in_bulk = 0.0          # In minutes (float with 1 decimal place)
        self._time_in_absorption = 0.0    # In minutes (float with 1 decimal place)
        self._time_in_float = 0.0         # In minutes (float with 1 decimal place)
        self._absorption_start_time = None  # epoch seconds; set when absorption phase begins
        
        # Day tracking for resetting daily counters
        self._last_day = datetime.now().day

        # Driver-memory peaks for register-based daily values.
        # Tracked with max/min guards so a controller register reset (which
        # happens at the controller's own clock midnight, potentially before
        # system midnight) cannot overwrite the real daily peak with 0.
        self._daily_yield       = 0.0
        self._daily_max_pv_v    = 0.0
        self._daily_min_batt_v  = 999.0   # will be pulled down on first tick
        self._daily_max_batt_v  = 0.0

        # Rolling daily history: list of dicts, index 0 = yesterday, max 30 entries.
        # Populated from the state file at startup; prepended to at midnight.
        self._history = []

        # State file path — written after each successful update so daily
        # accumulators survive a driver restart within the same calendar day.
        self._state_file = '/data/dbus-epever-tracer/state.json'

        # Restore accumulators from the previous run if the date still matches.
        self._load_state()

        # Value formatting for DBus display (adds units)
        _kwh = lambda p, v: (str(v) + 'kWh')
        _a = lambda p, v: (str(v) + 'A')
        _w = lambda p, v: (str(v) + 'W')
        _v = lambda p, v: (str(v) + 'V')
        _c = lambda p, v: (str(v) + '°C')

        logging.debug("%s /DeviceInstance = %d" % (servicename, deviceinstance))

        # Create the management objects (required by Victron DBus API)
        self._dbusservice.add_path('/Mgmt/ProcessName', __file__)
        self._dbusservice.add_path('/Mgmt/Connection', connection)

        # Create the mandatory device identification and status objects
        self._dbusservice.add_path('/DeviceInstance', deviceinstance)
        self._dbusservice.add_path('/ProductName', productname)
        self._dbusservice.add_path('/FirmwareVersion', firmwareversion)
        self._dbusservice.add_path('/Connected', 1)
        self._dbusservice.add_path('/Serial', serialnumber)

        # Network and BMS status (optional, for completeness)
        self._dbusservice.add_path('/Link/NetworkMode', 0)      # 0 = Standalone
        self._dbusservice.add_path('/Link/NetworkStatus', 4)    # 4 = Always connected
        self._dbusservice.add_path('/Settings/BmsPresent', 0)   # 0 = No BMS

        self._dbusservice.add_path('/Dc/0/Current', None, gettextcallback=_a)
        self._dbusservice.add_path('/Dc/0/Voltage', None, gettextcallback=_v)
        self._dbusservice.add_path('/Alarms/HighTemperature', 0)

        self._dbusservice.add_path('/State',None)
        self._dbusservice.add_path('/Pv/V', None, gettextcallback=_v)
        self._dbusservice.add_path('/Yield/Power', None, gettextcallback=_w)
        self._dbusservice.add_path('/Yield/User', None, gettextcallback=_kwh)
        self._dbusservice.add_path('/Yield/System', None, gettextcallback=_kwh)
        self._dbusservice.add_path('/Load/State',None, writeable=True)
        self._dbusservice.add_path('/Load/I',None, gettextcallback=_a)
        self._dbusservice.add_path('/ErrorCode', 0)
        self._dbusservice.add_path('/WarningCode', 0)

        # Historical statistics (overall and daily)
        self._dbusservice.add_path('/History/Overall/MaxPvVoltage', 0, gettextcallback=_v)
        self._dbusservice.add_path('/History/Overall/MinBatteryVoltage', 999, gettextcallback=_v)
        self._dbusservice.add_path('/History/Overall/MaxBatteryVoltage', 0, gettextcallback=_v)
        self._dbusservice.add_path('/History/Overall/DaysAvailable', 31)
        self._dbusservice.add_path('/History/Overall/LastError1', 0)

        # Today's statistics (Daily/0) — live values updated every tick
        self._dbusservice.add_path('/History/Daily/0/Yield', 0.0)
        self._dbusservice.add_path('/History/Daily/0/MaxPower', 0)
        self._dbusservice.add_path('/History/Daily/0/MaxPvVoltage', 0)
        self._dbusservice.add_path('/History/Daily/0/MinBatteryVoltage', 0)
        self._dbusservice.add_path('/History/Daily/0/MaxBatteryVoltage', 0)
        self._dbusservice.add_path('/History/Daily/0/MaxBatteryCurrent', 0)
        self._dbusservice.add_path('/History/Daily/0/TimeInBulk', 0)
        self._dbusservice.add_path('/History/Daily/0/TimeInAbsorption', 0)
        self._dbusservice.add_path('/History/Daily/0/TimeInFloat', 0)
        self._dbusservice.add_path('/History/Daily/0/LastError1', 0)

        # Historical days Daily/1 (yesterday) through Daily/30 — loaded from history list
        for _day in range(1, 31):
            self._dbusservice.add_path(f'/History/Daily/{_day}/Yield', 0.0)
            self._dbusservice.add_path(f'/History/Daily/{_day}/MaxPower', 0)
            self._dbusservice.add_path(f'/History/Daily/{_day}/MaxPvVoltage', 0)
            self._dbusservice.add_path(f'/History/Daily/{_day}/MinBatteryVoltage', 0)
            self._dbusservice.add_path(f'/History/Daily/{_day}/MaxBatteryVoltage', 0)
            self._dbusservice.add_path(f'/History/Daily/{_day}/MaxBatteryCurrent', 0)
            self._dbusservice.add_path(f'/History/Daily/{_day}/TimeInBulk', 0)
            self._dbusservice.add_path(f'/History/Daily/{_day}/TimeInAbsorption', 0)
            self._dbusservice.add_path(f'/History/Daily/{_day}/TimeInFloat', 0)
            self._dbusservice.add_path(f'/History/Daily/{_day}/LastError1', 0)
   
        # Restore today's in-memory max values and historical days from state file.
        self._dbusservice['/History/Daily/0/MaxPower'] = self._restored_daily_max_power
        self._dbusservice['/History/Daily/0/MaxBatteryCurrent'] = self._restored_daily_max_battery_current
        self._publish_history()

        # Temperature service — separate DBus service for the controller sensor.
        # Needs its own private bus connection; sharing one connection only allows
        # a single root '/' object-path registration and would raise a KeyError.
        self._tempservice = VeDbusService(tempservicename, bus=dbus.SystemBus(private=True))
        self._tempservice.add_path('/Mgmt/ProcessName', __file__)
        self._tempservice.add_path('/Mgmt/Connection', connection)
        self._tempservice.add_path('/DeviceInstance', temperature_deviceinstance)
        self._tempservice.add_path('/ProductName', productname + ' Temperature')
        self._tempservice.add_path('/Connected', 1)
        self._tempservice.add_path('/Temperature', None, gettextcallback=_c)
        self._tempservice.add_path('/TemperatureType', 0)  # 0 = battery

        # Switch service — exposes the load output as a controllable DC switch
        self._switchservice = VeDbusService(switchservicename, bus=dbus.SystemBus(private=True))
        self._switchservice.add_path('/Mgmt/ProcessName', __file__)
        self._switchservice.add_path('/Mgmt/Connection', connection)
        self._switchservice.add_path('/Mgmt/ProcessVersion', firmwareversion)
        self._switchservice.add_path('/DeviceInstance', 0)
        self._switchservice.add_path('/ProductName', productname + ' DC Load')
        self._switchservice.add_path('/Serial', serialnumber)
        self._switchservice.add_path('/Connected', 1)
        self._switchservice.add_path('/State', 256)
        self._switchservice.add_path('/ModuleVoltage', None, gettextcallback=_v)
        self._switchservice.add_path('/SwitchableOutput/output_1/State', None, writeable=True,
                                     onchangecallback=self._on_load_switch_change)
        self._switchservice.add_path('/SwitchableOutput/output_1/Status', 9)
        self._switchservice.add_path('/SwitchableOutput/output_1/Name', 'Load Output')
        self._switchservice.add_path('/SwitchableOutput/output_1/Current', None, gettextcallback=_a)
        self._switchservice.add_path('/SwitchableOutput/output_1/Settings/Group', '')
        self._switchservice.add_path('/SwitchableOutput/output_1/Settings/CustomName', '')
        self._switchservice.add_path('/SwitchableOutput/output_1/Settings/Function', 2)    # 2 = Manual control
        self._switchservice.add_path('/SwitchableOutput/output_1/Settings/ValidFunctions', 4)  # bit 2 = only Manual (hides Function row when only one option)
        self._switchservice.add_path('/SwitchableOutput/output_1/Settings/Type', 1)        # 1 = Toggle
        self._switchservice.add_path('/SwitchableOutput/output_1/Settings/ValidTypes', 2)  # bit 1 = only Toggle allowed
        self._switchservice.add_path('/SwitchableOutput/output_1/Settings/ShowUIControl', 1)  # 0=Off, 1=Always, 2=Only local, 3=Only on VRM

        # Schedule periodic data updates every 1000 ms (1 second)
        GLib.timeout_add(1000, self._update)

    def _on_load_switch_change(self, path, value):
        self._load_command = value
        # Optimistically update DBus immediately so the GUI doesn't bounce back
        # while waiting for the next read tick to confirm the new state.
        self._switchservice['/SwitchableOutput/output_1/State'] = value
        return True

    def _update(self):
        """Read registers and publish the latest values on DBus.

        The Tracer exposes most values in a set of Modbus holding registers. On
        every timer tick we read the required blocks, translate them into the
        units expected by Victron devices and push them onto the service object.
        Any communication failure is logged and after a number of consecutive
        errors the driver exits so that the supervisor can restart it.
        """


        try:
            # Read main data registers from EPEVER (see protocol docs for meaning)
            # REGISTER_PV_BATTERY (0x3100): PV array data registers (18 registers)
            # Contains: PV voltage, current, power, battery voltage/current/temp, etc.
            c3100 = controller.read_registers(REGISTER_PV_BATTERY, 18, 4)  # c3100[0-17]: Registers 0x3100-0x3111
            
            # REGISTER_CHARGER_STATE (0x3200): Battery and charging status registers (3 registers)
            # Contains: Battery status flags, charging status flags
            c3200 = controller.read_registers(REGISTER_CHARGER_STATE, 3, 4)  # c3200[0-2]: Registers 0x3200-0x3202
            
            # REGISTER_HISTORY (0x3300): Historical statistics registers (20 registers) 
            # Contains: Maximum and daily PV voltage, current, power, battery temp, generated energy
            c3300 = controller.read_registers(REGISTER_HISTORY, 20, 4)  # c3300[0-19]: Registers 0x3300-0x3313
           
            # REGISTER_HISTORY_DAILY (0x330C): Generated energy today (2 registers, cleared at midnight)
            # Contains: Today's generated energy (low word, high word)
            c330C = controller.read_registers(REGISTER_HISTORY_DAILY, 2, 4)  # c330C[0-1]: Registers 0x330C-0x330D

            # 0x9007: Boost/absorption setpoint; 0x9008: Float setpoint; 0x9009: Boost reconnect voltage
            charge_voltages = controller.read_registers(REGISTER_CHARGE_VOLTAGES, 3, 3)
            # 0x906C: Boost duration in minutes
            boost_duration_reg = controller.read_registers(REGISTER_BOOST_DURATION, 1, 3)
            # 0x2000: Discrete input — controller over-temperature flag (FC02)
            over_temp_bit = controller.read_bit(REGISTER_OVER_TEMP, 2)

            # Check lengths to avoid IndexError
            if not (len(c3100) >= 17 and len(c3200) >= 3 and len(c3300) >= 19 and len(c330C) >= 2 and len(charge_voltages) >= 3 and len(boost_duration_reg) >= 1):
                logging.warning("Modbus read returned unexpected data lengths.")
                return True
        except Exception as e:
            # On communication error, increment error counter and exit after 3 failures
            logging.exception("Exception occurred during Modbus read: %s", e)
            self._exception_counter += 1
            if self._exception_counter >= 3:
                logging.critical("Too many Modbus failures, exiting.")
                sys.exit(1)
            return True
        else:
            self._exception_counter = 0  # Reset on success
            # Prevent divide by zero for PV voltage (min 0.01 so PV current can be calculated)
            if c3100[0] < 1:
                c3100[0] = 1

            # Register assignments from EPEVER Tracer Modbus map:
            # c3100 registers from 0x3100 - PV array and battery data
            self._dbusservice['/Dc/0/Voltage'] = c3100[4]/100      # Register 0x3104: Battery voltage (V), divide by 100
            self._dbusservice['/Dc/0/Current'] = c3100[5]/100      # Register 0x3105: Battery charging current (A), divide by 100
            self._tempservice['/Temperature'] = c3100[17]/100  # Register 0x3111: Controller temperature (°C), divide by 100
            self._dbusservice['/Pv/V'] = c3100[0]/100              # Register 0x3100: PV array voltage (V), divide by 100
            self._dbusservice['/Yield/Power'] = round((c3100[2] | c3100[3] << 16)/100) # Registers 0x3102-0x3103: PV array charging power (W), divide by 100
            self._dbusservice['/Load/I'] = c3100[13]/100           # Register 0x310D: Load current (A), divide by 100

            # Calculate the Victron compatible error code from the EPEVER
            # battery and charger status registers.
            # c3200 registers from 0x3200 - Battery status and charging status
            # c3200[0] = Register 0x3200: Battery status (flags for over/under voltage, temperature, etc.)
            # c3200[1] = Register 0x3201: Charging status (flags for charging state, PV status, etc.)
            self._dbusservice['/ErrorCode'] = map_epever_error(c3200[0], c3200[1])
            self._dbusservice['/WarningCode'] = map_epever_warning(c3200[0])
            self._dbusservice['/Alarms/HighTemperature'] = 2 if over_temp_bit else 0  # 0x2000: 0=Normal, 2=Alarm

            # Map EPEVER charger state to Victron state for VRM compatibility.
            # Victron: 0=Off, 3=Bulk, 4=Absorption, 5=Float, 6=Equalise
            # EPEVER:  00=No charging, 01=Float, 10=Boost, 11=Equalizing
            # Bits 3–2 of register 0x3201 encode the EPEVER charging phase.
            #
            # EPEVER's "Boost" phase covers both Victron Bulk and Absorption:
            #   Bulk       — constant current, voltage rising toward absorption setpoint
            #   Absorption — voltage held at setpoint, current tapering; timed by 0x906C
            #
            # Absorption entry: EPEVER in Boost AND battery voltage reaches 0x9007.
            # Absorption exit:  voltage drops below boost-reconnect threshold (0x9009),
            #                   boost duration (0x906C minutes) has elapsed, or EPEVER
            #                   leaves Boost phase (controller took over transition).
            absorption_v    = charge_voltages[0] / 100   # 0x9007
            reconnect_v     = charge_voltages[2] / 100   # 0x9009
            boost_duration  = boost_duration_reg[0]      # 0x906C, minutes

            epever_phase  = _get_bit(c3200[1], 3) * 2 + _get_bit(c3200[1], 2)
            victron_state = state[epever_phase]

            if victron_state == 3:  # EPEVER Boost phase
                batt_v = self._dbusservice['/Dc/0/Voltage']
                if self._absorption_start_time is None:
                    # Not yet in absorption — check if we've reached the setpoint
                    if batt_v >= absorption_v:
                        self._absorption_start_time = time.time()
                        victron_state = 4
                else:
                    elapsed_minutes = (time.time() - self._absorption_start_time) / 60
                    if batt_v < reconnect_v:
                        # Voltage collapsed — heavy load or cloud; drop back to Bulk
                        self._absorption_start_time = None
                    elif elapsed_minutes >= boost_duration:
                        # Boost duration expired — controller should switch to Float soon
                        self._absorption_start_time = None
                    else:
                        victron_state = 4
            else:
                # EPEVER left Boost phase; clear absorption tracking
                self._absorption_start_time = None

            self._dbusservice['/State'] = victron_state
                
            # Use the resolved state for time tracking this tick
            current_state = victron_state
            
            # Update charge phase time tracking
            now = time.time()
            time_diff_minutes = (now - self._last_update_time) / 60  # Convert seconds to minutes as float
            
            # Increment the appropriate time counter based on charge state
            if self._current_charge_state == 3:  # Bulk
                self._time_in_bulk += time_diff_minutes
            elif self._current_charge_state == 4:  # Absorption
                self._time_in_absorption += time_diff_minutes
            elif self._current_charge_state == 5:  # Float
                self._time_in_float += time_diff_minutes

            # Check for day transition
            current_day = datetime.now().day
            if current_day != self._last_day:
                logging.info("New day detected — snapshotting today into history and resetting counters.")

                yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
                snapshot = {
                    'date':                yesterday,
                    'yield':               self._daily_yield,
                    'max_power':           self._dbusservice['/History/Daily/0/MaxPower'],
                    'max_pv_voltage':      self._daily_max_pv_v,
                    'min_battery_voltage': self._daily_min_batt_v,
                    'max_battery_voltage': self._daily_max_batt_v,
                    'max_battery_current': self._dbusservice['/History/Daily/0/MaxBatteryCurrent'],
                    'time_in_bulk':        round(self._time_in_bulk, 0),
                    'time_in_absorption':  round(self._time_in_absorption, 0),
                    'time_in_float':       round(self._time_in_float, 0),
                    'last_error':          self._dbusservice['/History/Daily/0/LastError1'],
                }
                self._history.insert(0, snapshot)
                self._history = self._history[:30]
                self._publish_history()

                # Reset today's counters
                self._time_in_bulk = 0.0
                self._time_in_absorption = 0.0
                self._time_in_float = 0.0
                self._absorption_start_time = None
                self._dbusservice['/History/Daily/0/MaxPower'] = 0
                self._dbusservice['/History/Daily/0/MaxBatteryCurrent'] = 0
                self._daily_yield      = 0.0
                self._daily_max_pv_v   = 0.0
                self._daily_min_batt_v = 999.0
                self._daily_max_batt_v = 0.0

                self._last_day = current_day
            
            # Update the DBus paths with accumulated times for today (rounded to 1 decimal place)
            self._dbusservice['/History/Daily/0/TimeInBulk'] = round(self._time_in_bulk, 0)
            self._dbusservice['/History/Daily/0/TimeInAbsorption'] = round(self._time_in_absorption, 0)
            self._dbusservice['/History/Daily/0/TimeInFloat'] = round(self._time_in_float, 0)
            
            # Store current state for next iteration
            self._current_charge_state = current_state
            self._last_update_time = now

            # Execute any pending load switch command after reads to avoid disturbing
            # the c3300 read timing. The GUI bounce is handled by the optimistic update
            # in _on_load_switch_change; the read below then confirms the actual state.
            load_command_sent = False
            if self._load_command is not None:
                cmd = self._load_command
                self._load_command = None
                load_command_sent = True
                try:
                    controller.write_bit(0x0002, cmd, 5)  # Coil 0x0002: Manual load control, 1=On, 0=Off
                except Exception as e:
                    logging.warning("Failed to write load coil 0x0002: %s", e)

            # Register 0x3202 D0: load on/off status
            load_state = c3200[2] & 1
            self._dbusservice['/Load/State'] = load_state
            self._switchservice['/ModuleVoltage'] = c3100[4]/100  # Register 0x3104: Battery voltage (V), divide by 100
            # On the tick where a command was sent, preserve the optimistic State value
            # set in the callback; the pre-write read would otherwise undo it for 1 tick.
            if not load_command_sent:
                self._switchservice['/SwitchableOutput/output_1/State'] = load_state
            self._switchservice['/SwitchableOutput/output_1/Status'] = 13 if (c3200[2] & 0x0F02) else 9  # 9=normal, 13=fault (D1/D8/D9/D10/D11 of 0x3202)
            self._switchservice['/SwitchableOutput/output_1/Current'] = c3100[13]/100  # Register 0x310D: Load current (A), divide by 100
            
            # Registers 0x3312-0x3313: Total generated energy (kWh), divide by 100
            # c3300 starts at 0x3300, so 0x3312 = index 18, 0x3313 = index 19
            self._dbusservice['/Yield/User'] = (c3300[18] | c3300[19] << 16)/100
            self._dbusservice['/Yield/System'] = (c3300[18] | c3300[19] << 16)/100
            
            # Registers 0x330C-0x330D: Generated energy today (kWh × 100).
            # The controller clears this at its own clock midnight, which may be
            # slightly before system midnight due to clock drift.  Use max() so
            # the peak value seen today is never lost to a controller register reset.
            reg_yield = (c330C[0] | c330C[1] << 16) / 100
            if reg_yield > self._daily_yield:
                self._daily_yield = reg_yield
            self._dbusservice['/History/Daily/0/Yield'] = self._daily_yield

            # Daily max/min voltages — seeded from controller registers but guarded
            # with max/min so a controller register reset before system midnight
            # cannot pull the tracked peak back to zero.
            reg_max_pv_v   = c3300[0] / 100
            reg_min_batt_v = c3300[3] / 100
            reg_max_batt_v = c3300[2] / 100

            if reg_max_pv_v   > self._daily_max_pv_v:   self._daily_max_pv_v   = reg_max_pv_v
            if reg_min_batt_v < self._daily_min_batt_v:  self._daily_min_batt_v = reg_min_batt_v
            if reg_max_batt_v > self._daily_max_batt_v:  self._daily_max_batt_v = reg_max_batt_v

            self._dbusservice['/History/Daily/0/MaxPvVoltage']      = self._daily_max_pv_v
            self._dbusservice['/History/Daily/0/MinBatteryVoltage'] = self._daily_min_batt_v
            self._dbusservice['/History/Daily/0/MaxBatteryVoltage'] = self._daily_max_batt_v

            # Overall lifetime max/min
            if self._daily_max_pv_v   > self._dbusservice['/History/Overall/MaxPvVoltage']:
                self._dbusservice['/History/Overall/MaxPvVoltage'] = self._daily_max_pv_v

            if self._daily_min_batt_v < self._dbusservice['/History/Overall/MinBatteryVoltage']:
                self._dbusservice['/History/Overall/MinBatteryVoltage'] = self._daily_min_batt_v

            if self._daily_max_batt_v > self._dbusservice['/History/Overall/MaxBatteryVoltage']:
                self._dbusservice['/History/Overall/MaxBatteryVoltage'] = self._daily_max_batt_v

            # Max power and max battery current have no controller registers — keep tracking in memory.
            if self._dbusservice['/Yield/Power'] > self._dbusservice['/History/Daily/0/MaxPower']:
                self._dbusservice['/History/Daily/0/MaxPower'] = self._dbusservice['/Yield/Power']

            if self._dbusservice['/Dc/0/Current'] > self._dbusservice['/History/Daily/0/MaxBatteryCurrent']:
                self._dbusservice['/History/Daily/0/MaxBatteryCurrent'] = self._dbusservice['/Dc/0/Current']

            self._save_state()

        return True

    # ------------------------------------------------------------------
    # State persistence helpers
    # ------------------------------------------------------------------

    def _publish_history(self):
        """Write self._history to DBus paths Daily/1 through Daily/30."""
        for i, entry in enumerate(self._history):
            day = i + 1
            self._dbusservice[f'/History/Daily/{day}/Yield']               = entry.get('yield', 0.0)
            self._dbusservice[f'/History/Daily/{day}/MaxPower']            = entry.get('max_power', 0)
            self._dbusservice[f'/History/Daily/{day}/MaxPvVoltage']        = entry.get('max_pv_voltage', 0)
            self._dbusservice[f'/History/Daily/{day}/MinBatteryVoltage']   = entry.get('min_battery_voltage', 0)
            self._dbusservice[f'/History/Daily/{day}/MaxBatteryVoltage']   = entry.get('max_battery_voltage', 0)
            self._dbusservice[f'/History/Daily/{day}/MaxBatteryCurrent']   = entry.get('max_battery_current', 0)
            self._dbusservice[f'/History/Daily/{day}/TimeInBulk']          = entry.get('time_in_bulk', 0)
            self._dbusservice[f'/History/Daily/{day}/TimeInAbsorption']    = entry.get('time_in_absorption', 0)
            self._dbusservice[f'/History/Daily/{day}/TimeInFloat']         = entry.get('time_in_float', 0)
            self._dbusservice[f'/History/Daily/{day}/LastError1']          = entry.get('last_error', 0)

    def _load_state(self):
        """Restore accumulators and history from the state file."""
        self._restored_daily_max_power = 0
        self._restored_daily_max_battery_current = 0
        try:
            with open(self._state_file, 'r') as f:
                s = json.load(f)
            # History is always loaded regardless of date so past days are available.
            self._history = s.get('history', [])[:30]
            if s.get('date') == datetime.now().strftime('%Y-%m-%d'):
                self._time_in_bulk    = s.get('time_in_bulk', 0.0)
                self._time_in_absorption = s.get('time_in_absorption', 0.0)
                self._time_in_float   = s.get('time_in_float', 0.0)
                self._restored_daily_max_power            = s.get('daily_max_power', 0)
                self._restored_daily_max_battery_current  = s.get('daily_max_battery_current', 0)
                self._absorption_start_time               = s.get('absorption_start_time', None)
                self._daily_yield      = s.get('daily_yield', 0.0)
                self._daily_max_pv_v   = s.get('daily_max_pv_voltage', 0.0)
                self._daily_min_batt_v = s.get('daily_min_battery_voltage', 999.0)
                self._daily_max_batt_v = s.get('daily_max_battery_voltage', 0.0)
                logging.info("Restored daily accumulators and history from state file.")
            else:
                logging.info("State file is from a previous day — history loaded, accumulators start fresh.")
        except FileNotFoundError:
            pass  # First run — no state file yet
        except Exception as e:
            logging.warning("Could not load state file: %s", e)

    def _save_state(self):
        """Persist accumulators and history to the state file atomically."""
        s = {
            'date':                     datetime.now().strftime('%Y-%m-%d'),
            'time_in_bulk':             self._time_in_bulk,
            'time_in_absorption':       self._time_in_absorption,
            'time_in_float':            self._time_in_float,
            'absorption_start_time':    self._absorption_start_time,
            'daily_max_power':          self._dbusservice['/History/Daily/0/MaxPower'],
            'daily_max_battery_current': self._dbusservice['/History/Daily/0/MaxBatteryCurrent'],
            'daily_yield':              self._daily_yield,
            'daily_max_pv_voltage':     self._daily_max_pv_v,
            'daily_min_battery_voltage': self._daily_min_batt_v,
            'daily_max_battery_voltage': self._daily_max_batt_v,
            'history':                  self._history,
        }
        tmp = self._state_file + '.tmp'
        try:
            with open(tmp, 'w') as f:
                json.dump(s, f)
            os.replace(tmp, self._state_file)  # atomic on Linux
        except Exception as e:
            logging.warning("Could not save state file: %s", e)




# ===============================
# Main entry point
# ===============================
def main():
    """Entry point when executed as a stand‑alone script.

    The service relies on the GLib main loop provided by ``dbus.mainloop.glib``
    for asynchronous DBus handling.  Once the service object has been created,
    control is handed over to GLib which keeps the process alive indefinitely.
    """

    logging.basicConfig(level=logging.DEBUG)
    logging.info(f"{__file__} is starting up")

    # Validate and open the serial port passed as the first CLI argument.
    if len(sys.argv) < 2:
        logging.critical("Usage: dbus-epever-tracer.py /dev/ttyUSBx")
        sys.exit(1)

    port = sys.argv[1]
    global controller, servicename, tempservicename, switchservicename
    try:
        controller = minimalmodbus.Instrument(port, 1)  # Modbus slave address 1
    except Exception as e:
        logging.critical("Cannot open serial port %s: %s", port, e)
        sys.exit(1)

    # Configure Modbus RTU connection parameters for EPEVER Tracer
    controller.serial.baudrate = 115200    # Standard baud rate for EPEVER
    controller.serial.bytesize = 8         # 8 data bits
    controller.serial.parity = serial.PARITY_NONE  # No parity
    controller.serial.stopbits = 1         # 1 stop bit
    controller.serial.timeout = 0.2        # 200 ms timeout
    controller.mode = minimalmodbus.MODE_RTU  # Use RTU (binary) mode
    controller.clear_buffers_before_each_transaction = True  # Prevents stale data

    # Flush any bytes left in the FT232R USB FIFO from a previous session.
    # The USB chip can hold buffered data after the previous process closes the
    # port; those bytes arrive with a small delay and corrupt the first read if
    # not discarded.  Two flushes with a pause between them drain both the kernel
    # buffer and any bytes still trickling out of the chip.
    controller.serial.reset_input_buffer()
    time.sleep(0.1)
    controller.serial.reset_input_buffer()

    # Build the DBus service names from the port's basename (e.g. ttyUSB0)
    servicename     = 'com.victronenergy.solarcharger.' + port.split('/')[-1]
    tempservicename = 'com.victronenergy.temperature.'  + port.split('/')[-1]
    switchservicename = 'com.victronenergy.switch.'     + port.split('/')[-1]

    from dbus.mainloop.glib import DBusGMainLoop
    # Set up the main loop so we can send/receive async calls to/from DBus
    DBusGMainLoop(set_as_default=True)

    # Now safe to open a DBus connection for timezone lookup
    _apply_venus_timezone()

    # Create the EPEVER DBus service instance
    epever = DbusEpever()

    logging.info('Connected to dbus, and switching over to GLib.MainLoop() (event based)')
    # Start the GLib event loop (runs forever)
    mainloop = GLib.MainLoop()
    mainloop.run()


# Run the main function if this script is executed directly
if __name__ == "__main__":
    main()
