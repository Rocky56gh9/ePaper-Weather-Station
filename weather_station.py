#!/usr/bin/env python3
"""Show current conditions, the next 12 hours, and a 3-day forecast on a Waveshare 3.52" e-Paper display.

    python3 weather_station.py                          fetch weather and update the display
    python3 weather_station.py --deep-clean             cycle the panel black/white first (nightly)
    python3 weather_station.py --force                  update even during quiet hours
    python3 weather_station.py --preview out.png        render to a PNG instead of the display
    python3 weather_station.py --demo --preview out.png use bundled sample data; no API key or hardware
"""
import argparse
import configparser
import fcntl
import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

import layout

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.ini"
SAMPLE_PATH = ROOT / "sample_data.json"
CACHE_PATH = ROOT / "last_forecast.json"     # last good API response, shown when offline
SHOWN_PATH = ROOT / ".last_display"          # fingerprint of the image on the panel
LOCK_PATH = ROOT / ".update.lock"

ONE_CALL_URL = "https://api.openweathermap.org/data/3.0/onecall"

# Callout thresholds when config.ini leaves them blank, in the configured units
DEFAULT_THRESHOLDS = {
    "imperial": {"wind": 15, "gusts": 25, "uv_index": 6, "temp_swing": 10},
    "metric": {"wind": 7, "gusts": 11, "uv_index": 6, "temp_swing": 6},
}

log = logging.getLogger("weather_station")


class StationError(Exception):
    """A problem the user can fix; the message says how."""


class FetchError(StationError):
    """OpenWeather couldn't be reached or refused the request; a cached forecast can stand in."""


def parse_hours(text, name):
    """Parse quiet_hours like "0-5" or "23-6" into (start, end), or None when blank."""
    text = text.strip()
    if not text:
        return None
    try:
        start, end = (int(part) for part in text.split("-"))
    except ValueError:
        raise StationError(f"{name} must look like 0-5 (start and end hour, 24-hour clock), or be blank.")
    if not (0 <= start <= 23 and 0 <= end <= 23):
        raise StationError(f"{name} hours must be between 0 and 23.")
    return start, end


def in_hours(hour, span):
    start, end = span
    return start <= hour < end if start <= end else hour >= start or hour < end


def load_config(path):
    if not path.exists():
        raise StationError(f"{path.name} not found. Run ./install.sh, or copy config.example.ini to config.ini and edit it.")
    parser = configparser.ConfigParser()
    parser.read(path)
    if "openweather" not in parser:
        raise StationError(f"{path.name} has no [openweather] section. Compare it with config.example.ini.")
    weather = parser["openweather"]
    display = parser["display"] if "display" in parser else {}

    api_key = weather.get("api_key", "").strip()
    if not api_key or api_key.startswith("YOUR_"):
        raise StationError(f"Set api_key in {path.name}.")
    try:
        lat, lon = float(weather["latitude"]), float(weather["longitude"])
    except (KeyError, ValueError):
        raise StationError(f"Set latitude and longitude in {path.name} as decimal numbers, e.g. 51.51 and -0.13.")
    units = weather.get("units", "imperial").strip().lower()
    if units not in DEFAULT_THRESHOLDS:
        raise StationError(f"units in {path.name} must be imperial or metric.")

    thresholds = dict(DEFAULT_THRESHOLDS[units])
    for key in thresholds:
        value = display.get(key, "").strip()
        if value:
            try:
                thresholds[key] = float(value)
            except ValueError:
                raise StationError(f"{key} in {path.name} must be a number, or blank for the default.")
    try:
        evening_starts = int(display.get("evening_starts", "18").strip() or 18)
    except ValueError:
        raise StationError(f"evening_starts in {path.name} must be an hour from 0 to 23.")

    return {
        "api_key": api_key, "lat": lat, "lon": lon, "units": units,
        "thresholds": thresholds,
        "quiet_hours": parse_hours(display.get("quiet_hours", ""), "quiet_hours"),
        "evening_starts": evening_starts,
    }


def fetch_weather(cfg):
    params = {
        "lat": cfg["lat"],
        "lon": cfg["lon"],
        "units": cfg["units"],
        "exclude": "minutely",
        "appid": cfg["api_key"],
    }
    # Error messages deliberately omit the request URL, which contains the API key
    try:
        resp = requests.get(ONE_CALL_URL, params=params, timeout=30)
    except requests.RequestException as e:
        raise FetchError(f"Could not reach OpenWeather ({type(e).__name__}). Check the network connection.") from None
    if resp.status_code == 401:
        raise StationError(
            "OpenWeather rejected the API key (401). One Call API 3.0 needs its own subscription on your "
            "account, and new keys can take a couple of hours to activate."
        )
    if resp.status_code != 200:
        raise FetchError(f"OpenWeather returned HTTP {resp.status_code}.")
    return resp.json()


def save_cache(data, fetched_at):
    tmp = CACHE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps({"fetched_at": fetched_at.timestamp(), "data": data}))
    os.replace(tmp, CACHE_PATH)  # atomic, so a power cut never leaves a half-written cache


def load_cache():
    try:
        cached = json.loads(CACHE_PATH.read_text())
        return cached["data"], datetime.fromtimestamp(cached["fetched_at"], timezone.utc)
    except (OSError, ValueError, KeyError):
        return None, None


def get_forecast(cfg, now):
    """Return (data, offline_since). Falls back to the cached forecast when OpenWeather is unreachable."""
    try:
        data = fetch_weather(cfg)
    except FetchError as e:
        data, fetched_at = load_cache()
        if data is None:
            raise
        log.warning("%s Showing the forecast from %s.", e, fetched_at.astimezone().strftime("%-m/%-d %-I:%M %p"))
        return data, fetched_at
    save_cache(data, now)
    return data, None


def show_on_display(image, deep_clean=False):
    # Imported here so --preview works on machines without the display or GPIO libraries
    from waveshare_epd import epd3in52

    epd = epd3in52.EPD()
    try:
        epd.init()
        if deep_clean:
            # Full black/white cycles exercise every pixel and clear ghosting from the static layout
            frame_bytes = epd.width * epd.height // 8
            for _ in range(2):
                for fill in (0x00, 0xFF):
                    epd.send_command(0x13)  # start frame data
                    epd.send_data2([fill] * frame_bytes)
                    epd.lut_GC()
                    epd.refresh()
        epd.display(epd.getbuffer(image))
        epd.lut_GC()
        epd.refresh()
    finally:
        epd.sleep()  # cuts panel power; leaving it powered can damage the display


def fingerprint(image):
    return hashlib.sha256(image.tobytes()).hexdigest()


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--preview", metavar="PNG", help="save the rendered screen to an image instead of the display")
    parser.add_argument("--demo", action="store_true", help="use sample_data.json instead of calling OpenWeather")
    parser.add_argument("--deep-clean", action="store_true", help="cycle the panel black and white before drawing")
    parser.add_argument("--force", action="store_true", help="update even during quiet hours or when nothing changed")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Cron can start a run while a slow one is still refreshing the panel; never drive it twice at once
    with open(LOCK_PATH, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log.warning("Another update is still running; skipping this one.")
            return 0
        return run(args)


def run(args):
    # Fetch and render before touching the panel, so a failure never blanks the screen
    try:
        if args.demo:
            data = json.loads(SAMPLE_PATH.read_text())
            # The sample is a fixed moment, so the demo renders identically every time
            now = datetime.fromtimestamp(data["current"]["dt"], timezone.utc)
            image = layout.render(data, "imperial", DEFAULT_THRESHOLDS["imperial"], now)
        else:
            cfg = load_config(CONFIG_PATH)
            now = datetime.now(timezone.utc)
            quiet = cfg["quiet_hours"]
            if quiet and in_hours(now.astimezone().hour, quiet) and not (args.force or args.deep_clean or args.preview):
                log.info("Quiet hours (%d:00-%d:00); leaving the display alone.", *quiet)
                return 0
            data, offline_since = get_forecast(cfg, now)
            image = layout.render(data, cfg["units"], cfg["thresholds"], now,
                                  evening_starts=cfg["evening_starts"], offline_since=offline_since)
    except StationError as e:
        log.error("%s", e)
        return 1
    except (KeyError, IndexError, TypeError) as e:
        log.error("Unexpected forecast data format (missing %s).", e)
        return 1

    if args.preview:
        image.save(args.preview)
        log.info("Saved preview to %s", args.preview)
        return 0

    # While offline the screen often wouldn't change; skip the refresh flash when it's identical
    shown = fingerprint(image)
    if not (args.force or args.deep_clean) and SHOWN_PATH.exists() and SHOWN_PATH.read_text() == shown:
        log.info("Screen unchanged; skipping refresh.")
        return 0
    show_on_display(image, deep_clean=args.deep_clean)
    SHOWN_PATH.write_text(shown)
    log.info("Display updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
