#!/bin/bash
# =============================================
# Epever Tracer DBus Driver Start Script
# =============================================
#
# Usage: start-dbus-epever-tracer.sh <tty device>
# Example: ./start-dbus-epever-tracer.sh ttyUSB0
#
# This script is intended to be run under a process supervisor (e.g., daemontools).
# If the Python driver exits (e.g., due to serial disconnect), the supervisor will restart it.
#
# Arguments:
#   $1 - Serial TTY device (e.g., ttyUSB0 or ttyS1)

set -e

# Source Victron serial-starter service functions
. /opt/victronenergy/serial-starter/run-service.sh

# Check for required TTY argument
if [ -z "$1" ]; then
    echo "Error: No serial device specified."
    echo "Usage: $0 <tty device> (e.g., ttyUSB0)"
    exit 1
fi

SERIAL_DEV="$1"

# Command to run the driver
app="python3 /opt/victronenergy/dbus-epever-tracer/dbus-epever-tracer.py /dev/$SERIAL_DEV"
echo "Starting Epever Tracer DBus driver on /dev/$SERIAL_DEV..."

# Start the service using the serial-starter framework
start /dev/$SERIAL_DEV
