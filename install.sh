#!/usr/bin/env bash
# One-time setup on the Raspberry Pi: config.ini, packages, display interfaces, and the cron schedule.
# Safe to re-run: it keeps an existing config.ini and replaces its own cron entries.
set -euo pipefail

DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
cd "$DIR"
CRON_TAG="# epaper-weather-station"

if ! grep -q "Raspberry Pi" /proc/device-tree/model 2>/dev/null; then
    echo "This doesn't look like a Raspberry Pi. install.sh sets up the Pi that drives the display." >&2
    echo "To try the layout on another machine: pip install pillow requests && python3 weather_station.py --demo --preview preview.png" >&2
    exit 1
fi

echo "==> Configuring"
config_ready=true
if [ -f config.ini ]; then
    echo "Keeping existing config.ini."
else
    cp config.example.ini config.ini
    chmod 600 config.ini
    if [ -t 0 ]; then
        echo "Which display is attached?"
        echo "  1) Waveshare 3.52\" e-Paper HAT"
        echo "  2) Pimoroni Inky wHAT"
        read -rp "Choice [1]: " choice
        until [[ "${choice:-1}" =~ ^[12]$ ]]; do read -rp "1 or 2: " choice; done
        [ "${choice:-1}" = 2 ] && screen=inky_what || screen=waveshare_3in52
        read -rp "OpenWeather API key: " api_key
        until [[ "$api_key" =~ ^[A-Za-z0-9]+$ ]]; do read -rp "Letters and digits only. API key: " api_key; done
        read -rp "Latitude (e.g. 51.51): " lat
        until [[ "$lat" =~ ^-?[0-9]+(\.[0-9]+)?$ ]]; do read -rp "Decimal number, please. Latitude: " lat; done
        read -rp "Longitude (e.g. -0.13): " lon
        until [[ "$lon" =~ ^-?[0-9]+(\.[0-9]+)?$ ]]; do read -rp "Decimal number, please. Longitude: " lon; done
        read -rp "Units: imperial or metric [imperial]: " units
        units="${units:-imperial}"
        until [[ "$units" =~ ^(imperial|metric)$ ]]; do read -rp "imperial or metric: " units; done
        sed -i -e "s/^screen = .*/screen = $screen/" \
               -e "s/^api_key = .*/api_key = $api_key/" \
               -e "s/^latitude = .*/latitude = $lat/" \
               -e "s/^longitude = .*/longitude = $lon/" \
               -e "s/^units = .*/units = $units/" config.ini
    else
        config_ready=false
        echo "Created config.ini. Edit it with your screen, API key, and location before the first update."
    fi
fi
screen="$(sed -nE 's/^screen *= *([a-z0-9_]+).*/\1/p' config.ini | head -1)"
screen="${screen:-waveshare_3in52}"
echo "Screen: $screen"

echo "==> Installing system packages"
packages=(python3-pil python3-requests python3-spidev)
if [ "$screen" = inky_what ]; then
    packages+=(python3-numpy)
    # A venv is only needed when inky isn't already installed for system Python (see below)
    python3 -c "import inky" 2>/dev/null || packages+=(python3-venv)
else
    packages+=(python3-gpiozero)
    # gpiozero needs a GPIO backend: lgpio on Bookworm and later, RPi.GPIO on older releases
    if apt-cache show python3-lgpio >/dev/null 2>&1; then
        packages+=(python3-lgpio)
    else
        packages+=(python3-rpi.gpio)
    fi
fi
sudo apt-get update -qq
sudo apt-get install -y "${packages[@]}"

echo "==> Enabling display interfaces"
reboot_needed=false
if [ -e /dev/spidev0.0 ]; then
    echo "SPI already enabled."
else
    sudo raspi-config nonint do_spi 0
    reboot_needed=true
fi
if [ "$screen" = inky_what ]; then
    # Inky identifies itself over I2C, and drives SPI chip select itself, so the kernel must release it
    if [ -e /dev/i2c-1 ]; then
        echo "I2C already enabled."
    else
        sudo raspi-config nonint do_i2c 0
        reboot_needed=true
    fi

    if python3 -c "import inky" 2>/dev/null; then
        # Keep a working install (e.g. inky 1.x from Pimoroni's older installer) rather than replacing it
        echo "Using the inky library already installed for system Python."
        python="$(command -v python3)"
    else
        echo "==> Installing Pimoroni's inky library"
        # inky 2.x drives SPI chip select itself, so the kernel must release it
        boot_config=/boot/firmware/config.txt
        [ -f "$boot_config" ] || boot_config=/boot/config.txt
        if grep -q "^dtoverlay=spi0-0cs" "$boot_config"; then
            echo "spi0-0cs overlay already set."
        else
            sudo cp "$boot_config" "$boot_config.bak-epaper-weather"
            echo "dtoverlay=spi0-0cs" | sudo tee -a "$boot_config" >/dev/null
            echo "Added dtoverlay=spi0-0cs to $boot_config (backup: $boot_config.bak-epaper-weather)."
            reboot_needed=true
        fi
        # Raspberry Pi OS keeps pip packages out of the system Python; a venv that can still see the apt packages
        [ -d .venv ] || python3 -m venv --system-site-packages .venv
        .venv/bin/pip install --upgrade inky
        python="$DIR/.venv/bin/python"
    fi
else
    python="$(command -v python3)"
fi

echo "==> Scheduling updates"
{
    crontab -l 2>/dev/null | grep -vF "$CRON_TAG" || true
    echo "*/15 * * * * $python \"$DIR/weather_station.py\" 2>&1 | logger -t epaper-weather $CRON_TAG"
    echo "10 1 * * * $python \"$DIR/weather_station.py\" --deep-clean 2>&1 | logger -t epaper-weather $CRON_TAG"
} | crontab -
echo "Updates every 15 minutes, plus a deep clean at 1:10am. Logs: journalctl -t epaper-weather"

if $reboot_needed; then
    echo
    echo "Display interfaces were just enabled. Reboot with 'sudo reboot'; the display updates within 15 minutes of startup."
elif $config_ready; then
    echo
    echo "==> First update"
    "$python" weather_station.py
fi
