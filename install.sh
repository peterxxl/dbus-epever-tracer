#!/bin/bash

# Prompt the user for confirmation before proceeding with the installation
read -p "Install Epever Solarcharger on Venus OS at your own risk? [Y to proceed]" -n 1 -r
echo    # Move to a new line for readability
if [[ $REPLY =~ ^[Yy]$ ]]
then
	# Step 1: Install Python pip3 and minimalmodbus library
	echo "Download and install pip3 and minimalmodbus"

	# Update opkg package list
	opkg update
	# Install Python3 pip
	opkg install python3-pip
	# Install or upgrade minimalmodbus Python library
	pip3 install -U minimalmodbus

	# Step 2: Download driver and supporting library
	echo "Download driver and library"

	# Change directory to /data for installation
	cd /data

	# Download and extract dbus-epever-tracer driver
	wget https://github.com/peterxxl/dbus-epever-tracer/archive/master.zip
	unzip master.zip
	rm master.zip

	# Download and extract velib_python library
	wget https://github.com/victronenergy/velib_python/archive/master.zip
	unzip master.zip
	rm master.zip

	# Step 3: Organize extracted files into the correct directories
	mkdir -p dbus-epever-tracer/ext/velib_python
    	cp -R dbus-epever-tracer-master/* dbus-epever-tracer
	cp -R velib_python-master/* dbus-epever-tracer/ext/velib_python

	# Remove the now-unneeded extracted folders
	rm -r velib_python-master
	rm -r dbus-epever-tracer-master

	# Step 4: Add service entries to serial-starter and udev rules
	echo "Add entries to serial-starter"
	cd ..
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
