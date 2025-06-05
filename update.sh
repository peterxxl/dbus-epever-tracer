#!/bin/bash

read -p "Update Epever Solarcharger on Venus OS at your own risk? [Y to proceed]" -n 1 -r
echo    # (optional) move to a new line
if [[ $REPLY =~ ^[Yy]$ ]]
then
	echo "Download driver and library"

	cd /data

	wget https://github.com/peterxxl/dbus-epever-tracer/archive/master.zip
	unzip master.zip
	rm master.zip

	wget https://github.com/victronenergy/velib_python/archive/master.zip
	unzip master.zip
	rm master.zip

	mkdir -p dbus-epever-tracer/ext/velib_python
    	cp -R dbus-epever-tracer-master/* dbus-epever-tracer
	cp -R velib_python-master/* dbus-epever-tracer/ext/velib_python

	rm -r velib_python-master
	rm -r dbus-epever-tracer-master

	echo "Install driver"
	chmod +x /data/dbus-epever-tracer/driver/start-dbus-epever-tracer.sh
	chmod +x /data/dbus-epever-tracer/driver/dbus-epever-tracer.py
	chmod +x /data/dbus-epever-tracer/service/run
	chmod +x /data/dbus-epever-tracer/service/log/run

	ln -s /data/dbus-epever-tracer/driver /opt/victronenergy/dbus-epever-tracer
	ln -s /data/dbus-epever-tracer/service /opt/victronenergy/service-templates/dbus-epever-tracer

	echo "To finish, reboot the Venus OS device"
fi
