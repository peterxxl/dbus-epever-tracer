#!/bin/bash

echo ""
echo "================================================="
echo "  Epever Tracer — Venus OS Updater"
echo "================================================="
echo ""

read -p "Update at your own risk. Proceed? [y/N] " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled. No changes were made."
    exit 0
fi

echo ""
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
cd /data

echo "[1/5] Downloading driver..."
wget -q --show-progress https://github.com/peterxxl/dbus-epever-tracer/archive/master.zip
unzip -q master.zip
rm master.zip
echo "      Done."

echo ""
echo "[2/5] Downloading Victron velib_python library..."
wget -q --show-progress https://github.com/victronenergy/velib_python/archive/master.zip
unzip -q master.zip
rm master.zip
echo "      Done."

echo ""
echo "[3/5] Installing files..."
mkdir -p dbus-epever-tracer/ext/velib_python
cp -R dbus-epever-tracer-master/* dbus-epever-tracer
cp -R velib_python-master/* dbus-epever-tracer/ext/velib_python
if [ "$SCRIPT_DIR" != "/data/dbus-epever-tracer" ]; then
    [ -f "$SCRIPT_DIR/update.sh" ]  && cp dbus-epever-tracer-master/update.sh  "$SCRIPT_DIR/update.sh"  && chmod +x "$SCRIPT_DIR/update.sh"
    [ -f "$SCRIPT_DIR/install.sh" ] && cp dbus-epever-tracer-master/install.sh "$SCRIPT_DIR/install.sh" && chmod +x "$SCRIPT_DIR/install.sh"
fi
rm -r velib_python-master dbus-epever-tracer-master
echo "      Done."

echo ""
echo "[4/5] Setting permissions..."
chmod +x /data/dbus-epever-tracer/setup.sh
chmod +x /data/dbus-epever-tracer/driver/start-dbus-epever-tracer.sh
chmod +x /data/dbus-epever-tracer/driver/dbus-epever-tracer.py
chmod +x /data/dbus-epever-tracer/service/run
chmod +x /data/dbus-epever-tracer/service/log/run
echo "      Done."

echo ""
echo "[5/5] Applying OS configuration (symlinks, serial-starter, udev, boot hook)..."
bash /data/dbus-epever-tracer/setup.sh
echo "      Done."

echo ""
echo "[+] Restarting driver..."
SVC=$(ls /service/ 2>/dev/null | grep dbus-epever-tracer | head -1)
if [ -n "$SVC" ]; then
    svc -t /service/"$SVC"
    echo "      Restarted: $SVC"
else
    echo "      No running service found — driver will start automatically when RS485 adapter is detected."
fi

echo ""
echo "================================================="
echo "  Update complete."
echo "================================================="
echo ""
