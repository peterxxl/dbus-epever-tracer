#!/bin/bash

# ===============================
# Epever Tracer Venus OS Installer
# ===============================
# This script installs the Epever Tracer driver and its dependencies on Venus OS.
# It will install required Python packages, download the driver and libraries,
# and organize everything for you. Use at your own risk!

read -p "Install Epever Tracer on Venus OS at your own risk? [Y to proceed]" -n 1 -r
echo    # Move to a new line for readability
if [[ $REPLY =~ ^[Yy]$ ]]
then
    echo "\n[1/6] Installing Python3 pip and minimalmodbus library..."
    # Update opkg package list
    opkg update
    # Install Python3 pip
    opkg install python3-pip
    # Install or upgrade minimalmodbus Python library
    pip3 install -U minimalmodbus

    echo "[2/6] Downloading latest dbus-epever-tracer driver..."
    cd /data
    wget -q --show-progress https://github.com/peterxxl/dbus-epever-tracer/archive/master.zip
    echo "Unzipping driver..."
    unzip -q master.zip
    rm master.zip

    echo "[3/6] Downloading latest Victron velib_python library..."
    wget -q --show-progress https://github.com/victronenergy/velib_python/archive/master.zip
    echo "Unzipping library..."
    unzip -q master.zip
    rm master.zip

    echo "[4/6] Organizing driver and library folders..."
    mkdir -p dbus-epever-tracer/ext/velib_python
    cp -R dbus-epever-tracer-master/* dbus-epever-tracer
    cp -R velib_python-master/* dbus-epever-tracer/ext/velib_python

    echo "Cleaning up temporary files..."
    rm -r velib_python-master
    rm -r dbus-epever-tracer-master

    echo "[5/6] Adding service entries to serial-starter and udev rules (if needed)..."
    cd ..
    # (Add your service/udev rule steps here if required)

    echo "[6/6] Installation complete!"
    echo "To finish, set up your serial device and reboot your Venus OS device."
else
    echo "\nInstallation cancelled by user. No changes were made."
fi
	# Add dbus-epever-tracer service entry to serial-starter.conf
	sed -i '/service.*imt.*dbus-imt-si-rs485tc/a service epever		dbus-epever-tracer' /etc/venus/serial-starter.conf
	# Add udev rule for USB Serial devices
	sed -i '$aACTION=="add", ENV{ID_BUS}=="usb", ENV{ID_MODEL}=="USB_Serial",          ENV{VE_SERVICE}="epever"' /etc/udev/rules.d/serial-starter.rules

	# Step 5: Make driver and service scripts executable
	echo "Install driver"
	chmod +x /data/dbus-epever-tracer/driver/start-dbus-epever-tracer.sh
	chmod +x /data/dbus-epever-tracer/driver/dbus-epever-tracer.py
	chmod +x /data/dbus-epever-tracer/service/run
	chmod +x /data/dbus-epever-tracer/service/log/run

	# Step 6: Create symbolic links for driver and service templates
	ln -s /data/dbus-epever-tracer/driver /opt/victronenergy/dbus-epever-tracer
	ln -s /data/dbus-epever-tracer/service /opt/victronenergy/service-templates/dbus-epever-tracer

	# Final step: Prompt user to reboot
	echo "To finish, reboot the Venus OS device"
fi
