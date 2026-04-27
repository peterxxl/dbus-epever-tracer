#!/bin/bash

# =============================================================================
# Epever Tracer — post-update OS configuration
# =============================================================================
# Recreates the symlinks, serial-starter entry, and udev rule that Venus OS
# wipes when the operating system is updated.
#
# This script is idempotent: it is safe to run multiple times.
#
# Boot hook strategy (two hooks are needed):
#   /data/rcS.local — early boot, before services start:
#       runs this script to put symlinks and config in place
#   /data/rc.local  — late boot, after services start:
#       retriggers udev so serial-starter picks up already-connected devices
# =============================================================================

DRIVER_DIR=/data/dbus-epever-tracer

# --- Python dependencies ------------------------------------------------------
# pip packages are installed on the root filesystem and wiped on every OS
# update. Reinstall minimalmodbus unconditionally so it is always present.
pip3 install -q minimalmodbus

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
# The FT232R chip is also used by Victron's own RS485 cable, so the existing
# rules file already has a rule for it (VE_SERVICE="rs485:default").  We
# remove any existing epever entries and append exactly one clean rule so that
# our rule is last and overrides the default for this chip.
UDEV_RULES=/etc/udev/rules.d/serial-starter.rules
sed -i '/# Epever Tracer/d' "$UDEV_RULES"
sed -i '/VE_SERVICE="epever"/d' "$UDEV_RULES"
printf '\n# Epever Tracer: auto-start for Victron Energy USB RS485 cable (FT232R chipset)\nACTION=="add", ENV{ID_BUS}=="usb", ENV{ID_MODEL}=="FT232R_USB_UART", ENV{VE_SERVICE}="epever"\n' >> "$UDEV_RULES"
udevadm control --reload-rules 2>/dev/null || true

# --- early boot hook ----------------------------------------------------------
# Registers this script in /data/rcS.local so it runs before services start.
# Venus OS runs rcS.local via /etc/rcS.d/S99custom-rc-early.sh (requires -x).
RCS_LOCAL=/data/rcS.local
if ! grep -q "dbus-epever-tracer/setup.sh" "$RCS_LOCAL" 2>/dev/null; then
    echo "bash $DRIVER_DIR/setup.sh" >> "$RCS_LOCAL"
fi
chmod +x "$RCS_LOCAL"

# --- late boot hook -----------------------------------------------------------
# Registers a udev retrigger in /data/rc.local which runs after services start.
# This handles the case where the RS485 adapter is already plugged in at boot:
# the udev "add" event fires during early boot before our rule exists, so
# serial-starter misses the device.  Retriggering udev late replays the event
# with our rule in place, and serial-starter picks up the device.
RC_LOCAL=/data/rc.local
if ! grep -q "udevadm trigger" "$RC_LOCAL" 2>/dev/null; then
    echo "udevadm trigger --action=add --subsystem-match=tty" >> "$RC_LOCAL"
fi
chmod +x "$RC_LOCAL"
