#!/bin/bash

# =============================================================================
# Epever Tracer — post-update OS configuration
# =============================================================================
# Recreates the symlinks, serial-starter entry, and udev rule that Venus OS
# wipes when the operating system is updated.
#
# This script is idempotent: it is safe to run multiple times.  It is called
# automatically at every boot via /data/rc.local so the driver survives OS
# updates without manual reinstallation.
#
# It can also be run manually at any time:
#   bash /data/dbus-epever-tracer/setup.sh
# =============================================================================

DRIVER_DIR=/data/dbus-epever-tracer

# --- Symlinks -----------------------------------------------------------------
# /opt/victronenergy is on the read-only root filesystem and is wiped on every
# OS update.  Recreate the symlinks the Venus OS service infrastructure needs.
ln -sf "$DRIVER_DIR/driver"  /opt/victronenergy/dbus-epever-tracer
ln -sf "$DRIVER_DIR/service" /opt/victronenergy/service-templates/dbus-epever-tracer

# --- serial-starter entry -----------------------------------------------------
# Tells serial-starter to launch our driver when it detects an RS485 device
# tagged as "epever" by the udev rule below.
SERIAL_CONF=/etc/venus/serial-starter.conf
if ! grep -q "dbus-epever-tracer" "$SERIAL_CONF" 2>/dev/null; then
    sed -i '/service.*imt.*dbus-imt-si-rs485tc/a service epever\t\tdbus-epever-tracer' "$SERIAL_CONF"
fi

# --- udev rule ----------------------------------------------------------------
# Marks the Victron Energy USB RS485 cable (FT232R chipset) as an "epever"
# device so serial-starter picks it up and launches the driver automatically.
UDEV_RULES=/etc/udev/rules.d/serial-starter.rules
if ! grep -q 'VE_SERVICE="epever"' "$UDEV_RULES" 2>/dev/null; then
    printf '\n\n# Epever Tracer: auto-start service for Victron Energy USB RS485 cable (FT232R chipset)\nACTION=="add", ENV{ID_BUS}=="usb", ENV{ID_MODEL}=="FT232R_USB_UART", ENV{VE_SERVICE}="epever"\n' >> "$UDEV_RULES"
    udevadm control --reload-rules 2>/dev/null || true
fi
