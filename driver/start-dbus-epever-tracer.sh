#!/bin/bash
# =============================================
# Epever Tracer DBus Driver Start Script
# =============================================
#
# This script is intended to be run under a process supervisor (e.g., daemontools).
# If the Python driver exits (e.g., due to serial disconnect), the supervisor will restart it.
#

# Source Victron serial-starter service functions
. /opt/victronenergy/serial-starter/run-service.sh

# Command to run the driver
app="python /opt/victronenergy/dbus-epever-tracer/dbus-epever-tracer.py"
start /dev/$tty