#!/usr/bin/env python3

# ------------------------------------------------------------------------------
# EPEVER Tracer DBus Service Driver for Venus OS
# ------------------------------------------------------------------------------
# This script provides a DBus service for integrating EPEVER Tracer solar charge
# controllers with Victron Energy's Venus OS. It communicates over Modbus RTU and
# exposes data in a format compatible with Victron's ecosystem (VRM, GX devices).
# ------------------------------------------------------------------------------

"""Driver for exposing EPEVER Tracer MPPT data on the system DBus.

This module integrates an EPEVER Tracer solar charge controller with Victron's
DBus-based ecosystem. It communicates with the controller over Modbus RTU and
publishes data using the interface expected by Victron tools (VRM, GX devices).
Running this service on a Venus OS device enables monitoring of the Tracer
controller.

Features
--------
* Real-time monitoring of charger, battery, PV parameters, and SOC.
* Historical statistics in VRM-compatible format.
* Automatic reconnection and error handling for serial failures.
* Support for manual load control.

References:
- Victron Energy DBus API: https://github.com/victronenergy/venus/wiki/dbus
- EPEVER Tracer Modbus Protocol: epsolar_modbus_protocol_map.pdf
"""

import minimalmodbus
import sys
import os
import logging
import time
import datetime
from gi.repository import GLib
import dbus
import dbus.service
import serial
import argparse

# Local library path setup
sys.path.insert(1, os.path.join(os.path.dirname(__file__), '../ext/velib_python'))
from vedbus import VeDbusService

# Global configuration
softwareversion = '0.9'
serialnumber = 'WO20160415-008-0056'
productname = 'EPEVER Tracer MPPT'
productid = 0xB001
customname = 'Solar Charger'
firmwareversion = 'v1.04'
connection = 'USB'
deviceinstance = 278
exception_counter = 0

# State mapping: EPEVER (D3-D2 of 0x3201) to Victron states
# EPEVER: 00 = No charging, 01 = Float, 10 = Boost, 03 = Equalization
# Victron: 0 = Off, 3 = Bulk, 4 = Absorption, 5 = Float, 7 = Equalization
STATE_MAP = {
    0: 0,  # No charging -> Off
    1: 5,  # Float -> Float
    2: 4,  # Boost -> Absorption
    3: 7   # Equalization -> Equalization
}

# Error mapping: EPEVER fault bits to Victron MPPT error codes
ERROR_MAP = {
    'no_error': 0,
    'battery_temp_high': 1,
    'battery_voltage_high': 2,
    'charger_temp_high': 17,
    'charger_over_current': 18,
    'charger_current_reversed': 19,
    'input_voltage_error': 20,
    'generic_fault': 38
}

def map_epever_error(batt_status, chg_status):
    """Translate EPEVER status bits to Victron MPPT error code."""
    # Battery status (0x3200)
    batt_state = batt_status & 0x000F
    if batt_state == 0x01:
        return ERROR_MAP['battery_voltage_high']
    if batt_state == 0x04:
        return ERROR_MAP['generic_fault']
    if batt_status & 0x0010:
        return ERROR_MAP['battery_temp_high']

    # Charger status (0x3201)
    inp_status = (chg_status >> 14) & 0x03
    if inp_status == 2:
        return ERROR_MAP['battery_voltage_high']
    if inp_status == 3:
        return ERROR_MAP['input_voltage_error']
    if chg_status & (1 << 13 | 1 << 12 | 1 << 11 | 1 << 7):
        return ERROR_MAP['charger_over_current']
    if chg_status & (1 << 10):
        return ERROR_MAP['charger_over_current']
    if chg_status & (1 << 8):
        return ERROR_MAP['generic_fault']
    if chg_status & (1 << 4):
        return ERROR_MAP['charger_current_reversed']

    return ERROR_MAP['no_error']

# Modbus RTU initialization
parser = argparse.ArgumentParser(description='EPEVER Tracer DBus Service')
parser.add_argument('port', help='Serial port (e.g., /dev/ttyUSB0)')
parser.add_argument('--slave', type=int, default=1, help='Modbus slave address (default: 1)')
args = parser.parse_args()

try:
    controller = minimalmodbus.Instrument(args.port, args.slave)
except serial.SerialException as e:
    logging.error(f"Failed to open serial port {args.port}: {e}")
    sys.exit(1)

# Generate unique DBus service name
servicename = 'com.victronenergy.solarcharger.' + args.port.split('/')[-1]

# Configure Modbus RTU
controller.serial.baudrate = 115200
controller.serial.bytesize = 8
controller.serial.parity = serial.PARITY_NONE
controller.serial.stopbits = 1
controller.serial.timeout = 0.2
controller.mode = minimalmodbus.MODE_RTU
controller.clear_buffers_before_each_transaction = True

# Modbus register addresses (from epsolar_modbus_protocol_map.pdf)
REGISTER_PV_BATTERY = 0x3100  # PV, battery, load data
REGISTER_STATUS = 0x3200      # Battery and charger status
REGISTER_HISTORY = 0x3300     # Historical data
REGISTER_DAILY_ENERGY = 0x330C  # Daily generated energy
REGISTER_VOLTAGES = 0x9007    # Boost and float voltages
REGISTER_CLOCK = 0x9013       # Real-time clock
COIL_LOAD_CONTROL = 0x0002    # Manual load control

logging.info(f"Starting {__file__} on {args.port}, slave ID {args.slave}")

class DbusEpever:
    def __init__(self):
        self._dbusservice = VeDbusService(servicename)
        
        # Time tracking
        self._last_update_time = time.time()
        self._current_charge_state = 0
        self._time_in_bulk = 0
        self._time_in_absorption = 0
        self._time_in_float = 0
        self._last_day = None
        
        # Yesterday's data
        self._yesterday_yield = 0.0
        self._yesterday_max_power = 0
        self._yesterday_max_pv_voltage = 0
        self._yesterday_min_battery_voltage = 0
        self._yesterday_max_battery_voltage = 0
        self._yesterday_time_in_bulk = 0
        self._yesterday_time_in_absorption = 0
        self._yesterday_time_in_float = 0

        # Value formatting
        _kwh = lambda p, v: f"{v} kWh"
        _a = lambda p, v: f"{v} A"
        _w = lambda p, v: f"{v} W"
        _v = lambda p, v: f"{v} V"
        _c = lambda p, v: f"{v} °C"
        _pct = lambda p, v: f"{v} %"

        logging.debug(f"{servicename} /DeviceInstance = {deviceinstance}")

        # Management objects
        self._dbusservice.add_path('/Mgmt/ProcessName', __file__)
        self._dbusservice.add_path('/Mgmt/ProcessVersion', softwareversion)
        self._dbusservice.add_path('/Mgmt/Connection', connection)

        # Device identification
        self._dbusservice.add_path('/DeviceInstance', deviceinstance)
        self._dbusservice.add_path('/ProductId', productid)
        self._dbusservice.add_path('/ProductName', productname)
        self._dbusservice.add_path('/FirmwareVersion', firmwareversion)
        self._dbusservice.add_path('/Connected', 1)
        self._dbusservice.add_path('/Serial', serialnumber)
        self._dbusservice.add_path('/CustomName', customname, writeable=True)

        # Network and BMS status
        self._dbusservice.add_path('/Link/NetworkMode', 0)
        self._dbusservice.add_path('/Link/NetworkStatus', 4)
        self._dbusservice.add_path('/Settings/BmsPresent', 0)

        # Real-time data
        self._dbusservice.add_path('/Dc/0/Current', None, gettextcallback=_a)
        self._dbusservice.add_path('/Dc/0/Voltage', None, gettextcallback=_v)
        self._dbusservice.add_path('/Soc', None, gettextcallback=_pct)
        self._dbusservice.add_path('/State', None)
        self._dbusservice.add_path('/Pv/V', None, gettextcallback=_v)
        self._dbusservice.add_path('/Yield/Power', None, gettextcallback=_w)
        self._dbusservice.add_path('/Yield/User', None, gettextcallback=_kwh)
        self._dbusservice.add_path('/Yield/System', None, gettextcallback=_kwh)
        self._dbusservice.add_path('/Load/State', None, writeable=True, onchangecallback=self._handle_load_state)
        self._dbusservice.add_path('/Load/I', None, gettextcallback=_a)
        self._dbusservice.add_path('/ErrorCode', 0)

        # Historical statistics
        self._dbusservice.add_path('/History/Overall/MaxPvVoltage', 0, gettextcallback=_v)
        self._dbusservice.add_path('/History/Overall/MinBatteryVoltage', 0, gettextcallback=_v)
        self._dbusservice.add_path('/History/Overall/MaxBatteryVoltage', 0, gettextcallback=_v)
        self._dbusservice.add_path('/History/Overall/DaysAvailable', 2)
        self._dbusservice.add_path('/History/Overall/LastError1', 0)

        # Today's statistics
        self._dbusservice.add_path('/History/Daily/0/Yield', 0.0, gettextcallback=_kwh)
        self._dbusservice.add_path('/History/Daily/0/MaxPower', 0, gettextcallback=_w)
        self._dbusservice.add_path('/History/Daily/0/MaxPvVoltage', 0, gettextcallback=_v)
        self._dbusservice.add_path('/History/Daily/0/MinBatteryVoltage', 0, gettextcallback=_v)
        self._dbusservice.add_path('/History/Daily/0/MaxBatteryVoltage', 0, gettextcallback=_v)
        self._dbusservice.add_path('/History/Daily/0/MaxBatteryCurrent', 0, gettextcallback=_a)
        self._dbusservice.add_path('/History/Daily/0/TimeInBulk', 0)
        self._dbusservice.add_path('/History/Daily/0/TimeInAbsorption', 0)
        self._dbusservice.add_path('/History/Daily/0/TimeInFloat', 0)
        self._dbusservice.add_path('/History/Daily/0/LastError1', 0)

        # Yesterday's statistics
        self._dbusservice.add_path('/History/Daily/1/Yield', 0.0, gettextcallback=_kwh)
        self._dbusservice.add_path('/History/Daily/1/MaxPower', 0, gettextcallback=_w)
        self._dbusservice.add_path('/History/Daily/1/MaxPvVoltage', 0, gettextcallback=_v)
        self._dbusservice.add_path('/History/Daily/1/MinBatteryVoltage', 0, gettextcallback=_v)
        self._dbusservice.add_path('/History/Daily/1/MaxBatteryVoltage', 0, gettextcallback=_v)
        self._dbusservice.add_path('/History/Daily/1/TimeInBulk', 0)
        self._dbusservice.add_path('/History/Daily/1/TimeInAbsorption', 0)
        self._dbusservice.add_path('/History/Daily/1/TimeInFloat', 0)
        self._dbusservice.add_path('/History/Daily/1/LastError1', 0)

        GLib.timeout_add(1000, self._update)

    def _handle_load_state(self, path, value):
        """Handle changes to /Load/State by writing to coil 0x0002."""
        try:
            controller.write_coil(COIL_LOAD_CONTROL, bool(value))
            return True
        except minimalmodbus.ModbusException as e:
            logging.error(f"Failed to set load state: {e}")
            return False

    def _update(self):
        """Read Modbus registers and update DBus paths."""
        global exception_counter
        try:
            # Read registers
            c3100 = controller.read_registers(REGISTER_PV_BATTERY, 26, 4)  # 0x3100-0x3119
            c3200 = controller.read_registers(REGISTER_STATUS, 2, 4)       # 0x3200-0x3201
            c3300 = controller.read_registers(REGISTER_HISTORY, 20, 4)     # 0x3300-0x3313
            c330c = controller.read_registers(REGISTER_DAILY_ENERGY, 2, 4) # 0x330C-0x330D
            c9007 = controller.read_registers(REGISTER_VOLTAGES, 2, 3)     # 0x9007-0x9008
            c9013 = controller.read_registers(REGISTER_CLOCK, 3, 3)        # 0x9013-0x9015

            if not (len(c3100) >= 26 and len(c3200) >= 2 and len(c3300) >= 20 and len(c330c) >= 2 and len(c9007) >= 2 and len(c9013) >= 3):
                logging.warning("Incomplete Modbus data")
                return True

            # Update DBus paths
            self._dbusservice['/Dc/0/Voltage'] = c3100[4] / 100
            self._dbusservice['/Dc/0/Current'] = c3100[5] / 100
            self._dbusservice['/Soc'] = c3100[26] / 100
            self._dbusservice['/Pv/V'] = c3100[0] / 100
            power = (c3100[3] << 16) | c3100[2] if c3100[0] > 0 else 0
            self._dbusservice['/Yield/Power'] = power / 100
            self._dbusservice['/Load/I'] = c3100[13] / 100
            self._dbusservice['/ErrorCode'] = map_epever_error(c3200[0], c3200[1])

            # Map charging state
            chg_state = (c3200[1] >> 2) & 0x03
            self._dbusservice['/State'] = STATE_MAP.get(chg_state, 0)
            if self._dbusservice['/State'] == 4 and self._dbusservice['/Dc/0/Voltage'] > c9007[1] / 100:
                self._dbusservice['/State'] = 4  # Confirm Absorption

            # Time tracking
            now = time.time()
            time_diff = int((now - self._last_update_time) / 60)  # Minutes
            if self._current_charge_state == 3:
                self._time_in_bulk += time_diff
            elif self._current_charge_state == 4:
                self._time_in_absorption += time_diff
            elif self._current_charge_state == 5:
                self._time_in_float += time_diff

            # Day transition (use controller clock)
            year = c9013[2] >> 8
            month = c9013[2] & 0xFF
            day = c9013[1] >> 8
            current_day = datetime.date(year + 2000, month, day).toordinal()
            if self._last_day is None:
                self._last_day = current_day
            if current_day != self._last_day:
                logging.info("New day, resetting daily counters")
                self._yesterday_yield = self._dbusservice['/History/Daily/0/Yield']
                self._yesterday_max_power = self._dbusservice['/History/Daily/0/MaxPower']
                self._yesterday_max_pv_voltage = self._dbusservice['/History/Daily/0/MaxPvVoltage']
                self._yesterday_min_battery_voltage = self._dbusservice['/History/Daily/0/MinBatteryVoltage']
                self._yesterday_max_battery_voltage = self._dbusservice['/History/Daily/0/MaxBatteryVoltage']
                self._yesterday_time_in_bulk = self._time_in_bulk
                self._yesterday_time_in_absorption = self._time_in_absorption
                self._yesterday_time_in_float = self._time_in_float

                self._dbusservice['/History/Daily/1/Yield'] = self._yesterday_yield
                self._dbusservice['/History/Daily/1/MaxPower'] = self._yesterday_max_power
                self._dbusservice['/History/Daily/1/MaxPvVoltage'] = self._yesterday_max_pv_voltage
                self._dbusservice['/History/Daily/1/MinBatteryVoltage'] = self._yesterday_min_battery_voltage
                self._dbusservice['/History/Daily/1/MaxBatteryVoltage'] = self._yesterday_max_battery_voltage
                self._dbusservice['/History/Daily/1/TimeInBulk'] = self._yesterday_time_in_bulk
                self._dbusservice['/History/Daily/1/TimeInAbsorption'] = self._yesterday_time_in_absorption
                self._dbusservice['/History/Daily/1/TimeInFloat'] = self._yesterday_time_in_float

                self._time_in_bulk = 0
                self._time_in_absorption = 0
                self._time_in_float = 0
                self._dbusservice['/History/Daily/0/MaxPower'] = 0
                self._dbusservice['/History/Daily/0/MaxPvVoltage'] = 0
                self._dbusservice['/History/Daily/0/MinBatteryVoltage'] = 0
                self._dbusservice['/History/Daily/0/MaxBatteryVoltage'] = 0
                self._dbusservice['/History/Daily/0/MaxBatteryCurrent'] = 0
                self._last_day = current_day

            self._dbusservice['/History/Daily/0/TimeInBulk'] = self._time_in_bulk
            self._dbusservice['/History/Daily/0/TimeInAbsorption'] = self._time_in_absorption
            self._dbusservice['/History/Daily/0/TimeInFloat'] = self._time_in_float
            self._current_charge_state = self._dbusservice['/State']
            self._last_update_time = now

            # Energy and statistics
            self._dbusservice['/Yield/User'] = ((c3300[13] << 16) | c3300[12]) / 100
            self._dbusservice['/Yield/System'] = ((c3300[13] << 16) | c3300[12]) / 100
            self._dbusservice['/History/Daily/0/Yield'] = ((c330c[1] << 16) | c330c[0]) / 100

            # Historical statistics
            if self._dbusservice['/Pv/V'] > self._dbusservice['/History/Overall/MaxPvVoltage']:
                self._dbusservice['/History/Overall/MaxPvVoltage'] = self._dbusservice['/Pv/V']
            if self._dbusservice['/Dc/0/Voltage'] and self._dbusservice['/Dc/0/Voltage'] < (self._dbusservice['/History/Overall/MinBatteryVoltage'] or float('inf')):
                self._dbusservice['/History/Overall/MinBatteryVoltage'] = self._dbusservice['/Dc/0/Voltage']
            if self._dbusservice['/Dc/0/Voltage'] > self._dbusservice['/History/Overall/MaxBatteryVoltage']:
                self._dbusservice['/History/Overall/MaxBatteryVoltage'] = self._dbusservice['/Dc/0/Voltage']

            if self._dbusservice['/Yield/Power'] > self._dbusservice['/History/Daily/0/MaxPower']:
                self._dbusservice['/History/Daily/0/MaxPower'] = self._dbusservice['/Yield/Power']
            if self._dbusservice['/Pv/V'] > self._dbusservice['/History/Daily/0/MaxPvVoltage']:
                self._dbusservice['/History/Daily/0/MaxPvVoltage'] = self._dbusservice['/Pv/V']
            if self._dbusservice['/Dc/0/Voltage'] and self._dbusservice['/Dc/0/Voltage'] < (self._dbusservice['/History/Daily/0/MinBatteryVoltage'] or float('inf')):
                self._dbusservice['/History/Daily/0/MinBatteryVoltage'] = self._dbusservice['/Dc/0/Voltage']
            if self._dbusservice['/Dc/0/Voltage'] > self._dbusservice['/History/Daily/0/MaxBatteryVoltage']:
                self._dbusservice['/History/Daily/0/MaxBatteryVoltage'] = self._dbusservice['/Dc/0/Voltage']
            if self._dbusservice['/Dc/0/Current'] > self._dbusservice['/History/Daily/0/MaxBatteryCurrent']:
                self._dbusservice['/History/Daily/0/MaxBatteryCurrent'] = self._dbusservice['/Dc/0/Current']

        except minimalmodbus.ModbusException as e:
            logging.warning(f"Modbus error: {e}")
            exception_counter += 1
            if exception_counter >= 3:
                logging.critical("Too many Modbus failures, exiting")
                sys.exit(1)
        except Exception as e:
            logging.error(f"Unexpected error: {e}")
            exception_counter += 1
            if exception_counter >= 3:
                sys.exit(1)

        return True

def main():
    logging.basicConfig(level=logging.INFO)
    from dbus.mainloop.glib import DBusGMainLoop
    DBusGMainLoop(set_as_default=True)
    epever = DbusEpever()
    logging.info("Connected to DBus, running GLib.MainLoop")
    mainloop = GLib.MainLoop()
    mainloop.run()

if __name__ == "__main__":
    main()