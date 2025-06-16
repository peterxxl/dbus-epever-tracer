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
import minimalmodbus
import sys
import os
import logging
import traceback
import time
import math
import datetime
from datetime import datetime, date
from asyncio import exceptions
import gettext
import time

# ===============================
# Standard library imports
# ===============================
import argparse
from gi.repository import GLib  # For main event loop
import dbus
import dbus.service  # For DBus service implementation
import serial  # For serial port handling

# ===============================
# Local library path setup
# ===============================
sys.path.insert(1, os.path.join(os.path.dirname(__file__), '../ext/velib_python'))

# ===============================
# Local application imports
# ===============================
from vedbus import VeDbusService  # Victron's DBus service implementation

# ===============================
# Global configuration variables
# ===============================
# These variables define the driver version, device identity, and service settings.
softwareversion = '0.9'
serialnumber = 'WO20160415-008-0056'
productname = 'Epever Tracer MPPT'
# productid = 0xA076
productid = 0xB001
customname = 'Cargador FV'
firmwareversion = 'v1.03'
connection = 'USB'
servicename = 'com.victronenergy.solarcharger.tty'
deviceinstance = 290    # VRM instance
exceptionCounter = 0
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

# ===============================
# Modbus RTU initialization
# ===============================
# The driver expects the serial port as a command-line argument.
# Example: python3 dbus-epever-tracer.py /dev/ttyUSB0
if len(sys.argv) > 1:
    controller = minimalmodbus.Instrument(sys.argv[1], 1)  # Modbus slave address 1
    # Generate a unique DBus service name based on the serial port
    servicename = 'com.victronenergy.solarcharger.' + sys.argv[1].split('/')[-1]
else:
    print("Error: No serial port specified. Usage: python3 dbus-epever-tracer.py /dev/ttyUSB0")
    sys.exit()

# Configure Modbus RTU connection parameters for EPEVER Tracer
# Modbus register addresses
REGISTER_PV_BATTERY = 0x3100  # PV array voltage, current, power, etc.
REGISTER_CHARGER_STATE = 0x3200  # Charging status, charging stage, etc.
REGISTER_HISTORY = 0x3300  # Historical generated energy data
REGISTER_HISTORY_DAILY = 0x330C  # Daily historical generated energy data
REGISTER_HISTORY_PREV_DAY = 0x3311  # Previous day's generated energy data
REGISTER_PARAMETERS = 0x9000  # Charging and load parameters
REGISTER_BOOST_VOLTAGE = 0x9002  # Boost voltage setpoint

# Only instantiate controller once, using the provided port
controller.serial.baudrate = 115200    # Standard baud rate for EPEVER
controller.serial.bytesize = 8         # 8 data bits
controller.serial.parity = serial.PARITY_NONE  # No parity
controller.serial.stopbits = 1         # 1 stop bit
controller.serial.timeout = 0.2        # 200 ms timeout
controller.mode = minimalmodbus.MODE_RTU  # Use RTU (binary) mode
controller.clear_buffers_before_each_transaction = True  # Prevents stale data



# Print startup message for debugging
logging.info(f"{__file__} is starting up, use -h argument to see optional arguments")

# ===============================
# Main DBus Service Class
# ===============================

class DbusEpever(object):
    def __init__(self, paths):
        """Create and register the DBus service.

        Parameters
        ----------
        paths : dict
            Dictionary of DBus paths.  It is kept for compatibility with
            other drivers but is currently unused.
        """
        self._dbusservice = VeDbusService(servicename)
        self._paths = paths
        
        # Variables for tracking charge state times
        self._last_update_time = time.time()
        self._current_charge_state = 0  # 0=Off, 3=Bulk, 4=Absorption, 5=Float, 7=Equalize
        self._time_in_bulk = 0.0        # In minutes
        self._time_in_absorption = 0.0   # In minutes
        self._time_in_float = 0.0       # In minutes
        self._time_in_equalization = 0.0 # In minutes
        
        # Day tracking for resetting daily counters
        self._last_day = datetime.now().day
        
        # Yesterday's data cache
        self._yesterday_yield = 0.0
        self._yesterday_max_power = 0
        self._yesterday_max_pv_voltage = 0
        self._yesterday_min_battery_voltage = 100
        self._yesterday_max_battery_voltage = 0
        self._yesterday_time_in_bulk = 0.0
        self._yesterday_time_in_absorption = 0.0
        self._yesterday_time_in_float = 0.0

        # Value formatting for DBus display (adds units)
        _kwh = lambda p, v: (str(v) + 'kWh')
        _a = lambda p, v: (str(v) + 'A')
        _w = lambda p, v: (str(v) + 'W')
        _v = lambda p, v: (str(v) + 'V')
        _c = lambda p, v: (str(v) + '°C')

        logging.debug("%s /DeviceInstance = %d" % (servicename, deviceinstance))

        # Create the management objects (required by Victron DBus API)
        self._dbusservice.add_path('/Mgmt/ProcessName', __file__)
        self._dbusservice.add_path('/Mgmt/ProcessVersion', softwareversion)
        self._dbusservice.add_path('/Mgmt/Connection', connection)

        # Create the mandatory device identification and status objects
        self._dbusservice.add_path('/DeviceInstance', deviceinstance)
        self._dbusservice.add_path('/ProductId', productid)
        self._dbusservice.add_path('/ProductName', productname)
        self._dbusservice.add_path('/FirmwareVersion', firmwareversion)
        self._dbusservice.add_path('/Connected', 1)
        self._dbusservice.add_path('/Serial', serialnumber)
        self._dbusservice.add_path('/CustomName', customname, writeable=True)

        # Network and BMS status (optional, for completeness)
        self._dbusservice.add_path('/Link/NetworkMode', 0)      # 0 = Standalone
        self._dbusservice.add_path('/Link/NetworkStatus', 4)    # 4 = Always connected
        self._dbusservice.add_path('/Settings/BmsPresent', 0)   # 0 = No BMS

        self._dbusservice.add_path('/Dc/0/Current', None, gettextcallback=_a)
        self._dbusservice.add_path('/Dc/0/Voltage', None, gettextcallback=_v)
        self._dbusservice.add_path('/Dc/0/Temperature', None, gettextcallback=_c)
        self._dbusservice.add_path('/State',None)
        self._dbusservice.add_path('/Pv/V', None, gettextcallback=_v)
        self._dbusservice.add_path('/Yield/Power', None, gettextcallback=_w)
        self._dbusservice.add_path('/Yield/User', None, gettextcallback=_kwh)
        self._dbusservice.add_path('/Yield/System', None, gettextcallback=_kwh)
        self._dbusservice.add_path('/Load/State',None, writeable=True)
        self._dbusservice.add_path('/Load/I',None, gettextcallback=_a)
        self._dbusservice.add_path('/ErrorCode',0)
        self._dbusservice.add_path('/WarningCode',0)

        # Historical statistics (overall and daily)
        self._dbusservice.add_path('/History/Overall/MaxPvVoltage', 0, gettextcallback=_v)         # Max PV voltage seen
        self._dbusservice.add_path('/History/Overall/MinBatteryVoltage', 100, gettextcallback=_v)  # Min battery voltage seen
        self._dbusservice.add_path('/History/Overall/MaxBatteryVoltage', 0, gettextcallback=_v)    # Max battery voltage seen
        self._dbusservice.add_path('/History/Overall/DaysAvailable', 2)                           # Number of days data available
        self._dbusservice.add_path('/History/Overall/LastError1', 0)                              # Last error code

        # Today's statistics (Daily/0)
        self._dbusservice.add_path('/History/Daily/0/Yield', 0.0)                                 # Today's yield (kWh)
        self._dbusservice.add_path('/History/Daily/0/MaxPower',0)                                 # Max power today (W)
        self._dbusservice.add_path('/History/Daily/0/MaxPvVoltage', 0)                            # Max PV voltage today (V)
        self._dbusservice.add_path('/History/Daily/0/MinBatteryVoltage', 100)                     # Min battery voltage today (V)
        self._dbusservice.add_path('/History/Daily/0/MaxBatteryVoltage', 0)                       # Max battery voltage today (V)
        self._dbusservice.add_path('/History/Daily/0/MaxBatteryCurrent', 0)                       # Max battery current today (A)
        self._dbusservice.add_path('/History/Daily/0/TimeInBulk', 0)                           # Time in bulk charge phase (min)
        self._dbusservice.add_path('/History/Daily/0/TimeInAbsorption', 0)                     # Time in absorption (min)
        self._dbusservice.add_path('/History/Daily/0/TimeInFloat', 0)                          # Time in float (min)
        self._dbusservice.add_path('/History/Daily/0/LastError1', 0)                              # Last error today
        
        # Yesterday's statistics (Daily/1)
        self._dbusservice.add_path('/History/Daily/1/Yield', 0.0)                                 # Yesterday's yield (kWh)
        self._dbusservice.add_path('/History/Daily/1/MaxPower',0)                                 # Max power yesterday (W)
        self._dbusservice.add_path('/History/Daily/1/MaxPvVoltage', 0)                            # Max PV voltage yesterday (V)
        self._dbusservice.add_path('/History/Daily/1/MinBatteryVoltage', 100)                     # Min battery voltage yesterday (V)
        self._dbusservice.add_path('/History/Daily/1/MaxBatteryVoltage', 0)                       # Max battery voltage yesterday (V)
        self._dbusservice.add_path('/History/Daily/1/TimeInBulk', 0)                           # Time in bulk charge phase yesterday (min)
        self._dbusservice.add_path('/History/Daily/1/TimeInAbsorption', 0)                     # Time in absorption yesterday (min)
        self._dbusservice.add_path('/History/Daily/1/TimeInFloat', 0)                          # Time in float yesterday (min)
        #self._dbusservice.add_path('/History/Daily/0/Nr', 1)  # Uncomment for advanced daily tracking

        #self._dbusservice.add_path('/100/Relay/0/State', 1, writeable=True)

        # Schedule periodic data updates every 1000 ms (1 second)
        GLib.timeout_add(1000, self._update)

    def _update(self):
        """Read registers and publish the latest values on DBus.

        The Tracer exposes most values in a set of Modbus holding registers. On
        every timer tick we read the required blocks, translate them into the
        units expected by Victron devices and push them onto the service object.
        Any communication failure is logged and after a number of consecutive
        errors the driver exits so that the supervisor can restart it.
        """

        # Helper to test individual bits in the state registers returned by the
        # controller. ``num`` is the integer value, ``i`` the bit position.
        def getBit(num, i):
            return ((num & (1 << i)) != 0)

        global exceptionCounter
        try:
            # Read main data registers from EPEVER (see protocol docs for meaning)
            c3100 = controller.read_registers(REGISTER_PV_BATTERY, 18, 4)  # PV, battery, load, temp, etc.
            c3200 = controller.read_registers(REGISTER_CHARGER_STATE, 3, 4)   # Charger state, load state
            c3300 = controller.read_registers(REGISTER_HISTORY, 20, 4)  # Historical counters
            # Read previous day's energy data (registers 0x3311-0x3312 for previous day energy yield)
            c3310 = controller.read_registers(REGISTER_HISTORY_PREV_DAY, 2, 4)  # Previous day's data

            # Read boost and float charging voltages
            boostchargingvoltage = controller.read_registers(REGISTER_BOOST_VOLTAGE, 2, 3)
            #logging.info(f"boost charging voltage: {boostchargingvoltage[0]}, float charging voltage: {boostchargingvoltage[1]}")

            # Check lengths to avoid IndexError
            if not (len(c3100) >= 17 and len(c3200) >= 3 and len(c3300) >= 19 and len(c3310) >= 2 and len(boostchargingvoltage) >= 2):
                logging.warning("Modbus read returned unexpected data lengths.")
                return True
        except Exception as e:
            # On communication error, increment error counter and exit after 3 failures
            logging.exception("Exception occurred during Modbus read: %s", e)
            exceptionCounter += 1
            if exceptionCounter >= 3:
                logging.critical("Too many Modbus failures, exiting.")
                sys.exit(1)
            return True
        else:
            exceptionCounter = 0  # Reset on success
            # Prevent divide by zero for PV voltage (min 0.01 so PV current can be calculated)
            if c3100[0] < 1:
                c3100[0] = 1

            self._dbusservice['/Dc/0/Voltage'] = c3100[4]/100
            self._dbusservice['/Dc/0/Current'] = c3100[5]/100.0
            self._dbusservice['/Dc/0/Temperature'] = c3100[16]/100
            self._dbusservice['/Pv/V'] = c3100[0]/100
            self._dbusservice['/Yield/Power'] = round((c3100[2] | c3100[3] << 8)/100)
            self._dbusservice['/Load/I'] = c3100[13]/100

            # Calculate the Victron compatible error code from the EPEVER
            # battery and charger status registers.
            self._dbusservice['/ErrorCode'] = map_epever_error(c3200[0], c3200[1])

            # Map EPEVER charger state to Victron state for VRM compatibility
            # Victron: 0=Off, 2=Fault, 3=Bulk, 4=Absorption, 5=Float, 6=Storage, 7=Equalize
            # Epever:  00=No charging, 01=Float, 10=Boost, 11=Equalizing
            self._dbusservice['/State'] = state[getBit(c3200[1],3)* 2 + getBit(c3200[1],2)]
            # Special case: if in Bulk and battery voltage > float set Absorption
            if self._dbusservice['/State'] == 3 and self._dbusservice['/Dc/0/Voltage'] > boostchargingvoltage[1]/100:
                self._dbusservice['/State'] = 4
                
            # Get current state for time tracking
            current_state = self._dbusservice['/State']
            
            # Update charge phase time tracking
            now = time.time()
            time_diff_minutes = (now - self._last_update_time) / 60.0  # Convert seconds to minutes
            
            # Increment the appropriate time counter based on charge state
            if self._current_charge_state == 3:  # Bulk
                self._time_in_bulk += time_diff_minutes
            elif self._current_charge_state == 4:  # Absorption
                self._time_in_absorption += time_diff_minutes
            elif self._current_charge_state == 5:  # Float
                self._time_in_float += time_diff_minutes
            elif self._current_charge_state == 7:  # Equalization
                self._time_in_equalization += time_diff_minutes
                
            # Check for day transition and reset counters if needed
            current_day = datetime.now().day
            if current_day != self._last_day:
                # Day has changed - move today's data to yesterday's before resetting
                logging.info("New day detected, resetting daily counters and saving yesterday's data")
                
                # Save today's accumulated values as yesterday's values
                # For yield, we use the current day's value since yesterday's yield is not available in Epever registers
                self._yesterday_yield = self._dbusservice['/History/Daily/0/Yield']
                self._yesterday_max_power = self._dbusservice['/History/Daily/0/MaxPower']
                self._yesterday_max_pv_voltage = self._dbusservice['/History/Daily/0/MaxPvVoltage']
                self._yesterday_min_battery_voltage = self._dbusservice['/History/Daily/0/MinBatteryVoltage']
                self._yesterday_max_battery_voltage = self._dbusservice['/History/Daily/0/MaxBatteryVoltage']
                self._yesterday_time_in_bulk = self._time_in_bulk
                self._yesterday_time_in_absorption = self._time_in_absorption
                self._yesterday_time_in_float = self._time_in_float
                
                # Update yesterday's paths
                self._dbusservice['/History/Daily/1/Yield'] = self._yesterday_yield
                self._dbusservice['/History/Daily/1/MaxPower'] = self._yesterday_max_power
                self._dbusservice['/History/Daily/1/MaxPvVoltage'] = self._yesterday_max_pv_voltage
                self._dbusservice['/History/Daily/1/MinBatteryVoltage'] = self._yesterday_min_battery_voltage
                self._dbusservice['/History/Daily/1/MaxBatteryVoltage'] = self._yesterday_max_battery_voltage
                self._dbusservice['/History/Daily/1/TimeInBulk'] = round(self._yesterday_time_in_bulk, 2)
                self._dbusservice['/History/Daily/1/TimeInAbsorption'] = round(self._yesterday_time_in_absorption, 2)
                self._dbusservice['/History/Daily/1/TimeInFloat'] = round(self._yesterday_time_in_float, 2)
                
                # Reset today's counters
                self._time_in_bulk = 0.0
                self._time_in_absorption = 0.0
                self._time_in_float = 0.0
                self._time_in_equalization = 0.0
                self._dbusservice['/History/Daily/0/MaxPower'] = 0
                self._dbusservice['/History/Daily/0/MaxPvVoltage'] = 0
                self._dbusservice['/History/Daily/0/MinBatteryVoltage'] = 100
                self._dbusservice['/History/Daily/0/MaxBatteryVoltage'] = 0
                self._dbusservice['/History/Daily/0/MaxBatteryCurrent'] = 0
                
                # Update day tracking
                self._last_day = current_day
            
            # Update the DBus paths with accumulated times for today
            self._dbusservice['/History/Daily/0/TimeInBulk'] = round(self._time_in_bulk, 2)
            self._dbusservice['/History/Daily/0/TimeInAbsorption'] = round(self._time_in_absorption, 2)
            self._dbusservice['/History/Daily/0/TimeInFloat'] = round(self._time_in_float, 2)
            
            # Store current state for next iteration
            self._current_charge_state = current_state
            self._last_update_time = now

            self._dbusservice['/Load/State'] = c3200[2]
            self._dbusservice['/Yield/User'] = (c3300[18] | c3300[19] << 8)/100
            self._dbusservice['/Yield/System'] = (c3300[18] | c3300[19] << 8)/100
            self._dbusservice['/History/Daily/0/Yield'] = (c3300[12] | c3300[13] << 8)/100
            
            # Update yesterday's yield from EPEVER registers
            yesterday_yield = (c3310[0] | c3310[1] << 8)/100
            if yesterday_yield > 0:
                self._dbusservice['/History/Daily/1/Yield'] = yesterday_yield

            # Update historical max/min statistics (overall and daily)
            if self._dbusservice['/Pv/V'] > self._dbusservice['/History/Overall/MaxPvVoltage']:
                self._dbusservice['/History/Overall/MaxPvVoltage'] = self._dbusservice['/Pv/V']

            if self._dbusservice['/Dc/0/Voltage'] < self._dbusservice['/History/Overall/MinBatteryVoltage']:
                self._dbusservice['/History/Overall/MinBatteryVoltage'] = self._dbusservice['/Dc/0/Voltage']

            if self._dbusservice['/Dc/0/Voltage'] > self._dbusservice['/History/Overall/MaxBatteryVoltage']:
                self._dbusservice['/History/Overall/MaxBatteryVoltage'] = self._dbusservice['/Dc/0/Voltage']

            # Daily statistics
            if self._dbusservice['/Yield/Power'] > self._dbusservice['/History/Daily/0/MaxPower']:
                self._dbusservice['/History/Daily/0/MaxPower'] = self._dbusservice['/Yield/Power']

            if self._dbusservice['/Pv/V'] > self._dbusservice['/History/Daily/0/MaxPvVoltage']:
                self._dbusservice['/History/Daily/0/MaxPvVoltage'] = self._dbusservice['/Pv/V']

            if self._dbusservice['/Dc/0/Voltage'] < self._dbusservice['/History/Daily/0/MinBatteryVoltage']:
                self._dbusservice['/History/Daily/0/MinBatteryVoltage'] = self._dbusservice['/Dc/0/Voltage']

            if self._dbusservice['/Dc/0/Voltage'] > self._dbusservice['/History/Daily/0/MaxBatteryVoltage']:
                self._dbusservice['/History/Daily/0/MaxBatteryVoltage'] = self._dbusservice['/Dc/0/Voltage']

            if self._dbusservice['/Dc/0/Current'] > self._dbusservice['/History/Daily/0/MaxBatteryCurrent']:
                self._dbusservice['/History/Daily/0/MaxBatteryCurrent'] = self._dbusservice['/Dc/0/Current']

        return True




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

    from dbus.mainloop.glib import DBusGMainLoop
    # Set up the main loop so we can send/receive async calls to/from DBus
    DBusGMainLoop(set_as_default=True)

    # Create the EPEVER DBus service instance
    epever = DbusEpever(paths = None)

    logging.info('Connected to dbus, and switching over to GLib.MainLoop() (event based)')
    # Start the GLib event loop (runs forever)
    mainloop = GLib.MainLoop()
    mainloop.run()


# Run the main function if this script is executed directly
if __name__ == "__main__":
    main()
