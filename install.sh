#!/usr/bin/env bash
# One-time setup on the Raspberry Pi: system packages, SPI, config.ini, and the cron schedule.
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

echo "==> Installing system packages"
packages=(python3-pil python3-requests python3-spidev python3-gpiozero)
# gpiozero needs a GPIO backend: lgpio on Bookworm and later, RPi.GPIO on older releases
if apt-cache show python3-lgpio >/dev/null 2>&1; then
    packages+=(python3-lgpio)
else
    packages+=(python3-rpi.gpio)
fi
sudo apt-get update -qq
sudo apt-get install -y "${packages[@]}"

echo "==> Enabling SPI"
reboot_needed=false
if [ -e /dev/spidev0.0 ]; then
    echo "SPI already enabled."
else
    sudo raspi-config nonint do_spi 0
    reboot_needed=true
fi

echo "==> Configuring"
config_ready=true
if [ -f config.ini ]; then
    echo "Keeping existing config.ini."
else
    cp config.example.ini config.ini
    chmod 600 config.ini
    if [ -t 0 ]; then
        read -rp "OpenWeather API key: " api_key
        until [[ "$api_key" =~ ^[A-Za-z0-9]+$ ]]; do read -rp "Letters and digits only. API key: " api_key; done
        read -rp "Latitude (e.g. 51.51): " lat
        until [[ "$lat" =~ ^-?[0-9]+(\.[0-9]+)?$ ]]; do read -rp "Decimal number, please. Latitude: " lat; done
        read -rp "Longitude (e.g. -0.13): " lon
        until [[ "$lon" =~ ^-?[0-9]+(\.[0-9]+)?$ ]]; do read -rp "Decimal number, please. Longitude: " lon; done
        read -rp "Units: imperial, metric, or standard [imperial]: " units
        units="${units:-imperial}"
        until [[ "$units" =~ ^(imperial|metric|standard)$ ]]; do read -rp "imperial, metric, or standard: " units; done
        sed -i -e "s/^api_key = .*/api_key = $api_key/" \
               -e "s/^latitude = .*/latitude = $lat/" \
               -e "s/^longitude = .*/longitude = $lon/" \
               -e "s/^units = .*/units = $units/" config.ini
    else
        config_ready=false
        echo "Created config.ini. Edit it with your API key and location before the first update."
    fi
fi

echo "==> Scheduling updates"
python="$(command -v python3)"
{
    crontab -l 2>/dev/null | grep -vF "$CRON_TAG" || true
    echo "*/15 * * * * $python \"$DIR/weather_station.py\" 2>&1 | logger -t epaper-weather $CRON_TAG"
    echo "10 1 * * * $python \"$DIR/weather_station.py\" --deep-clean 2>&1 | logger -t epaper-weather $CRON_TAG"
} | crontab -
echo "Updates every 15 minutes, plus a deep clean at 1:10am. Logs: journalctl -t epaper-weather"

if $reboot_needed; then
    echo
    echo "SPI was just enabled. Reboot with 'sudo reboot'; the display updates within 15 minutes of startup."
elif $config_ready; then
    echo
    echo "==> First update"
    "$python" weather_station.py
fi
