#!/bin/bash

# ===============================
# Epever Tracer Venus OS Installer
# ===============================
# Tested with Victron Energy USB RS485 cable (FT232R chipset)
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
    # Create directory for velib_python library and copy files
    mkdir -p dbus-epever-tracer/ext/velib_python
    cp -R dbus-epever-tracer-master/* dbus-epever-tracer
    cp -R velib_python-master/* dbus-epever-tracer/ext/velib_python

    echo "[5/6] Cleaning up temporary files and adding service entries..."
    # Remove temporary files
    rm -r velib_python-master
    rm -r dbus-epever-tracer-master
    # Add dbus-epever-tracer service entry to serial-starter.conf
    cd ..
    sed -i '/service.*imt.*dbus-imt-si-rs485tc/a service epever		dbus-epever-tracer' /etc/venus/serial-starter.conf
    # Add udev rule for Victron Energy USB RS485 cable (FT232R chipset)
    sed -i '$a\n\n# Epever Tracer: auto-start service for Victron Energy USB RS485 cable (FT232R chipset)\nACTION=="add", ENV{ID_BUS}=="usb", ENV{ID_MODEL}=="FT232R_USB_UART",            ENV{VE_SERVICE}="epever"' /etc/udev/rules.d/serial-starter.rules

    # Step 5: Make driver and service scripts executable
    echo "[6/6] Finalizing installation..."
    chmod +x /data/dbus-epever-tracer/driver/start-dbus-epever-tracer.sh
    chmod +x /data/dbus-epever-tracer/driver/dbus-epever-tracer.py
    chmod +x /data/dbus-epever-tracer/service/run
    chmod +x /data/dbus-epever-tracer/service/log/run

    # Create symbolic links for driver and service templates
    ln -s /data/dbus-epever-tracer/driver /opt/victronenergy/dbus-epever-tracer
    ln -s /data/dbus-epever-tracer/service /opt/victronenergy/service-templates/dbus-epever-tracer

    echo "[6/6] Installation complete!"
	
	# Final step: Prompt user to reboot
    echo "To finish, reboot the Venus OS device"
else
    echo "\nInstallation cancelled by user. No changes were made."
fi
