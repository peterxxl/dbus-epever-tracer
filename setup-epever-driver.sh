#!/bin/bash

DRIVER_DIR=/data/dbus-epever-tracer
GITHUB_DRIVER=https://github.com/peterxxl/dbus-epever-tracer/archive/master.zip
GITHUB_VELIB=https://github.com/victronenergy/velib_python/archive/master.zip
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
SCRIPT_NAME=$(basename "$0")

is_installed() {
    [ -f "$DRIVER_DIR/driver/dbus-epever-tracer.py" ]
}

echo ""
echo "================================================="
echo "  Epever Tracer — Venus OS Driver Setup"
echo "  Tested with Victron Energy USB RS485 cable"
echo "================================================="
echo ""

# ─── Menu ─────────────────────────────────────────────────────────────────────

if is_installed; then
    echo "Status: installed"
    echo ""
    echo "  1) Update to latest version"
    echo "  2) Remove from system"
    echo "  3) Cancel"
    echo ""
    read -p "Choose [1/2/3]: " -n 1 -r CHOICE
    echo ""
    case "$CHOICE" in
        1) ACTION=update ;;
        2) ACTION=remove ;;
        *) echo "Cancelled."; exit 0 ;;
    esac
else
    echo "Status: not installed"
    echo ""
    read -p "Install at your own risk. Proceed? [y/N] " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Cancelled. No changes were made."
        exit 0
    fi
    ACTION=install
fi

# ─── Remove ───────────────────────────────────────────────────────────────────

do_remove() {
    echo "The following changes will be made:"
    echo "  - Driver service(s) stopped and removed from supervision"
    echo "  - Symlinks removed from /opt/victronenergy/"
    echo "  - epever entry removed from /etc/venus/serial-starter.conf"
    echo "  - Udev rule removed from /etc/udev/rules.d/serial-starter.rules"
    echo "  - Boot hook entries removed from /data/rcS.local and /data/rc.local"
    echo "  - serial-starter restarted to reassign the serial port"
    echo ""
    read -p "Continue? [y/N] " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Cancelled. Nothing was changed."
        exit 0
    fi

    echo ""
    echo "[1/5] Stopping driver service(s)..."
    for SVC in $(ls /service/ 2>/dev/null | grep dbus-epever-tracer); do
        svc -d "/service/$SVC" 2>/dev/null || true
        sleep 1
        # Release the serial-starter lock for this TTY so it can be reassigned
        TTY="${SVC#dbus-epever-tracer.}"
        rm -f "/var/lock/serial-starter/$TTY"
        # Remove the service symlink and the volatile copy
        rm -f "/service/$SVC"
        rm -rf "/var/volatile/services/$SVC"
    done
    echo "      Done."

    echo ""
    echo "[2/5] Removing symlinks from /opt/victronenergy/..."
    rm -f /opt/victronenergy/dbus-epever-tracer
    rm -f /opt/victronenergy/service-templates/dbus-epever-tracer
    echo "      Done."

    echo ""
    echo "[3/5] Removing serial-starter entry..."
    # Only removes the exact line we added; leaves the rest of the file intact.
    sed -i '/service[[:space:]]*epever[[:space:]]*dbus-epever-tracer/d' \
        /etc/venus/serial-starter.conf
    echo "      Done."

    echo ""
    echo "[4/5] Removing udev rule and boot hooks..."
    # Udev rule — remove the comment and the rule line we appended.
    sed -i '/# Epever Tracer/d' /etc/udev/rules.d/serial-starter.rules
    sed -i '/VE_SERVICE.*="epever"/d' /etc/udev/rules.d/serial-starter.rules
    udevadm control --reload-rules 2>/dev/null || true
    # Boot hooks — remove only the lines this script added.
    if [ -f /data/rcS.local ]; then
        sed -i '/dbus-epever-tracer\/setup.sh/d' /data/rcS.local
    fi
    if [ -f /data/rc.local ]; then
        sed -i '/dbus-epever-tracer\/setup.sh/d' /data/rc.local
        sed -i '/udevadm trigger --action=add --subsystem-match=tty/d' /data/rc.local
    fi
    echo "      Done."

    echo ""
    echo "[5/5] Restarting serial-starter..."
    # serial-starter will re-evaluate the serial port using the updated rules.
    svc -t /service/serial-starter 2>/dev/null || true
    echo "      Done."

    echo ""
    read -p "Also delete driver files in $DRIVER_DIR? [y/N] " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "$DRIVER_DIR"
        echo "      Files deleted."
    else
        echo "      Files kept at $DRIVER_DIR"
        echo "      (run this script again to reinstall)"
    fi

    echo ""
    echo "================================================="
    echo "  Driver removed successfully."
    echo "================================================="
    echo ""
}

# ─── Helpers ──────────────────────────────────────────────────────────────────

# Download a zip from $1 and extract it; exits the script on failure.
download_and_extract() {
    local url=$1
    local label=$2
    rm -f master.zip
    if ! wget -q --show-progress "$url" -O master.zip; then
        echo "      ERROR: download failed ($label)."
        rm -f master.zip
        exit 1
    fi
    if ! unzip -q master.zip; then
        echo "      ERROR: failed to extract archive ($label)."
        rm -f master.zip
        exit 1
    fi
    rm master.zip
}

# ─── Install / Update ─────────────────────────────────────────────────────────

do_install_update() {
    cd /data

    if [ "$ACTION" = install ]; then
        echo ""
        echo "[1/5] Downloading driver..."
        download_and_extract "$GITHUB_DRIVER" "driver"
        echo "      Done."

        echo ""
        echo "[2/5] Downloading Victron velib_python library..."
        download_and_extract "$GITHUB_VELIB" "velib_python"
        echo "      Done."

        echo ""
        echo "[3/5] Installing files..."
        mkdir -p dbus-epever-tracer/ext/velib_python
        cp -R dbus-epever-tracer-master/* dbus-epever-tracer
        cp -R velib_python-master/* dbus-epever-tracer/ext/velib_python
        if [ "$SCRIPT_DIR" != "/data/dbus-epever-tracer" ] && [ -f "$SCRIPT_DIR/$SCRIPT_NAME" ]; then
            cp "dbus-epever-tracer-master/$SCRIPT_NAME" "$SCRIPT_DIR/$SCRIPT_NAME" \
                && chmod +x "$SCRIPT_DIR/$SCRIPT_NAME"
        fi
        rm -r velib_python-master dbus-epever-tracer-master
        echo "      Done."

        echo ""
        echo "[4/5] Setting permissions..."
        chmod +x /data/dbus-epever-tracer/setup-epever-driver.sh
        chmod +x /data/dbus-epever-tracer/setup.sh
        chmod +x /data/dbus-epever-tracer/driver/start-dbus-epever-tracer.sh
        chmod +x /data/dbus-epever-tracer/driver/dbus-epever-tracer.py
        chmod +x /data/dbus-epever-tracer/service/run
        chmod +x /data/dbus-epever-tracer/service/log/run
        echo "      Done."

        echo ""
        echo "[5/5] Applying OS configuration (symlinks, serial-starter, udev, boot hooks)..."
        bash /data/dbus-epever-tracer/setup.sh
        echo "      Done."

        echo ""
        echo "[+] Starting driver..."
        svc -t /service/serial-starter
        sleep 3
        SVC=$(ls /service/ 2>/dev/null | grep dbus-epever-tracer | head -n 1)
        if [ -n "$SVC" ]; then
            echo "      Driver started: $SVC"
        else
            echo "      RS485 adapter not detected yet — plug it in and the driver will start automatically."
        fi

    else  # update

        echo ""
        echo "[1/5] Downloading driver..."
        download_and_extract "$GITHUB_DRIVER" "driver"
        echo "      Done."

        echo ""
        echo "[2/5] Downloading Victron velib_python library..."
        download_and_extract "$GITHUB_VELIB" "velib_python"
        echo "      Done."

        echo ""
        echo "[3/5] Installing files..."
        mkdir -p dbus-epever-tracer/ext/velib_python
        cp -R dbus-epever-tracer-master/* dbus-epever-tracer
        cp -R velib_python-master/* dbus-epever-tracer/ext/velib_python
        if [ "$SCRIPT_DIR" != "/data/dbus-epever-tracer" ] && [ -f "$SCRIPT_DIR/$SCRIPT_NAME" ]; then
            cp "dbus-epever-tracer-master/$SCRIPT_NAME" "$SCRIPT_DIR/$SCRIPT_NAME" \
                && chmod +x "$SCRIPT_DIR/$SCRIPT_NAME"
        fi
        rm -r velib_python-master dbus-epever-tracer-master
        echo "      Done."

        echo ""
        echo "[4/5] Setting permissions..."
        chmod +x /data/dbus-epever-tracer/setup-epever-driver.sh
        chmod +x /data/dbus-epever-tracer/setup.sh
        chmod +x /data/dbus-epever-tracer/driver/start-dbus-epever-tracer.sh
        chmod +x /data/dbus-epever-tracer/driver/dbus-epever-tracer.py
        chmod +x /data/dbus-epever-tracer/service/run
        chmod +x /data/dbus-epever-tracer/service/log/run
        echo "      Done."

        echo ""
        echo "[5/5] Applying OS configuration (symlinks, serial-starter, udev, boot hooks)..."
        bash /data/dbus-epever-tracer/setup.sh
        echo "      Done."

        echo ""
        echo "[+] Restarting driver..."
        SVC=$(ls /service/ 2>/dev/null | grep dbus-epever-tracer | head -n 1)
        if [ -n "$SVC" ]; then
            svc -t "/service/$SVC"
            echo "      Restarted: $SVC"
        else
            echo "      No running service found — driver will start automatically when RS485 adapter is detected."
        fi

    fi

    echo ""
    echo "================================================="
    [ "$ACTION" = update ] && echo "  Update complete." || echo "  Installation complete."
    echo "================================================="
    echo ""
}

# ─── Dispatch ─────────────────────────────────────────────────────────────────

case "$ACTION" in
    remove)         do_remove ;;
    install|update) do_install_update ;;
esac
