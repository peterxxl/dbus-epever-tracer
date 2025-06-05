#!/usr/bin/env python3

# ------------------------------------------------------------------------------
# EPEVER Tracer DBus Service Driver for Venus OS
# ------------------------------------------------------------------------------
# This script provides a DBus service for integrating EPEVER Tracer solar charge
# controllers with Victron Energy's Venus OS. It communicates over Modbus RTU and
# exposes data in a format compatible with Victron's ecosystem (VRM, GX devices).
# ------------------------------------------------------------------------------

"""
DBus service for EPEVER Tracer solar charge controller integration with Venus OS.

This module implements a DBus service that communicates with an EPEVER Tracer solar
charge controller using Modbus RTU protocol and exposes the data on the system DBus
following the Victron Energy standards. This allows integration with the Venus OS
environment and other Victron Energy products.

Features:
- Real-time monitoring of solar charge controller parameters
- Standardized DBus interface compatible with Venus OS
- Support for Modbus RTU communication
- Automatic reconnection on communication errors

References:
- Victron Energy DBus API: https://github.com/victronenergy/venus/wiki/dbus
- EPEVER Tracer Modbus Protocol: Consult EPEVER Tracer documentation
"""


# ===============================
# Standard library imports
# ===============================
import sys
import os
import logging
import platform
import argparse
from asyncio import exceptions
import gettext

# ===============================
# Third-party imports
# ===============================
from gi.repository import GLib  # For main event loop
import dbus
import dbus.service  # For DBus service implementation
import minimalmodbus  # For Modbus RTU communication
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
productid = 0xA076
customname = 'PV Charger'
firmwareversion = 'v1.0'
connection = 'USB'
servicename = 'com.victronenergy.solarcharger.tty'
deviceinstance = 290    # VRM instance
exceptionCounter = 0
# State mapping for EPEVER to Victron charger states:
# Indexes: [00 01 10 11] where bits are [discharge, charge]
# 00 = No charging, 01 = Float, 10 = Boost, 11 = Equalizing
# Maps to Victron states: 0=Off, 5=Float, 3=Bulk, 6=Storage
state = [0,5,3,6]

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
# Modbus register addresses (for clarity and maintainability)
REGISTER_PV_BATTERY = 0x3100
REGISTER_CHARGER_STATE = 0x3200
REGISTER_HISTORY = 0x3300
REGISTER_BOOST_VOLTAGE = 0x9007

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
        """
        Initialize the DBus service instance.

        :param paths: Not used in this implementation.
        """
        self._dbusservice = VeDbusService(servicename)
        self._paths = paths

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

        # Historical statistics (overall and daily)
        self._dbusservice.add_path('/History/Overall/MaxPvVoltage', 0, gettextcallback=_v)         # Max PV voltage seen
        self._dbusservice.add_path('/History/Overall/MinBatteryVoltage', 100, gettextcallback=_v)  # Min battery voltage seen
        self._dbusservice.add_path('/History/Overall/MaxBatteryVoltage', 0, gettextcallback=_v)    # Max battery voltage seen
        self._dbusservice.add_path('/History/Overall/DaysAvailable', 1)                           # Number of days data available
        self._dbusservice.add_path('/History/Overall/LastError1', 0)                              # Last error code

        self._dbusservice.add_path('/History/Daily/0/Yield', 0.0)                                 # Today's yield (kWh)
        self._dbusservice.add_path('/History/Daily/0/MaxPower',0)                                 # Max power today (W)
        self._dbusservice.add_path('/History/Daily/0/MaxPvVoltage', 0)                            # Max PV voltage today (V)
        self._dbusservice.add_path('/History/Daily/0/MinBatteryVoltage', 100)                     # Min battery voltage today (V)
        self._dbusservice.add_path('/History/Daily/0/MaxBatteryVoltage', 0)                       # Max battery voltage today (V)
        self._dbusservice.add_path('/History/Daily/0/MaxBatteryCurrent', 0)                       # Max battery current today (A)
        self._dbusservice.add_path('/History/Daily/0/TimeInBulk', 0.01)                           # Time in bulk charge phase (h)
        self._dbusservice.add_path('/History/Daily/0/TimeInAbsorption', 0.01)                     # Time in absorption (h)
        self._dbusservice.add_path('/History/Daily/0/TimeInFloat', 0.01)                          # Time in float (h)
        self._dbusservice.add_path('/History/Daily/0/LastError1', 0)                              # Last error today
        #self._dbusservice.add_path('/History/Daily/0/Nr', 1)  # Uncomment for advanced daily tracking

        #self._dbusservice.add_path('/100/Relay/0/State', 1, writeable=True)

        # Schedule periodic data updates every 1000 ms (1 second)
        GLib.timeout_add(1000, self._update)

    def _update(self):
        """
        Periodic update function. Reads Modbus registers from the EPEVER controller
        and updates all DBus paths with the latest values. Handles exceptions and
        communication errors gracefully.
        """

        def getBit(num, i):
            return ((num & (1 << i)) != 0)

        global exceptionCounter
        try:
            # Read main data registers from EPEVER (see protocol docs for meaning)
            c3100 = controller.read_registers(REGISTER_PV_BATTERY, 18, 4)  # PV, battery, load, temp, etc.
            c3200 = controller.read_registers(REGISTER_CHARGER_STATE, 3, 4)   # Charger state, load state
            c3300 = controller.read_registers(REGISTER_HISTORY, 20, 4)  # Historical counters

            # Read boost and float charging voltages
            boostchargingvoltage = controller.read_registers(REGISTER_BOOST_VOLTAGE, 2, 3)
            #logging.info(f"boost charging voltage: {boostchargingvoltage[0]}, float charging voltage: {boostchargingvoltage[1]}")

            # Check lengths to avoid IndexError
            if not (len(c3100) >= 17 and len(c3200) >= 3 and len(c3300) >= 19 and len(boostchargingvoltage) >= 2):
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

            # Map EPEVER charger state to Victron state for VRM compatibility
            # Victron: 0=Off, 2=Fault, 3=Bulk, 4=Absorption, 5=Float, 6=Storage, 7=Equalize
            # Epever:  00=No charging, 01=Float, 10=Boost, 11=Equalizing
            self._dbusservice['/State'] = state[getBit(c3200[1],3)* 2 + getBit(c3200[1],2)]
            # Special case: if in Bulk and battery voltage > float set Absorption
            if self._dbusservice['/State'] == 3 and self._dbusservice['/Dc/0/Voltage'] > boostchargingvoltage[1]/100:
                self._dbusservice['/State'] = 4

            self._dbusservice['/Load/State'] = c3200[2]
            self._dbusservice['/Yield/User'] = (c3300[18] | c3300[19] << 8)/100
            self._dbusservice['/Yield/System'] = (c3300[18] | c3300[19] << 8)/100
            self._dbusservice['/History/Daily/0/Yield'] = (c3300[12] | c3300[13] << 8)/100

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
