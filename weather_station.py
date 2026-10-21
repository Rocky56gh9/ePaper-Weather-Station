#!/usr/bin/env python3
"""Show current conditions and a 3-day forecast on a Waveshare 3.52" e-Paper display.

    python3 weather_station.py                          fetch weather and update the display
    python3 weather_station.py --deep-clean             cycle the panel black/white first (nightly)
    python3 weather_station.py --preview out.png        render to a PNG instead of the display
    python3 weather_station.py --demo --preview out.png use bundled sample data; no API key or hardware
"""
import argparse
import configparser
import fcntl
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.ini"
SAMPLE_PATH = ROOT / "sample_data.json"
LOCK_PATH = ROOT / ".update.lock"
FONT_REGULAR = ROOT / "fonts" / "DejaVuSans.ttf"
FONT_BOLD = ROOT / "fonts" / "DejaVuSans-Bold.ttf"

WIDTH, HEIGHT = 360, 240  # landscape; the panel itself is 240x360 portrait
ONE_CALL_URL = "https://api.openweathermap.org/data/3.0/onecall"
UNIT_SYMBOLS = {"imperial": "°F", "metric": "°C", "standard": "K"}

log = logging.getLogger("weather_station")


class StationError(Exception):
    """A problem the user can fix; the message says how."""


def load_config(path):
    if not path.exists():
        raise StationError(f"{path.name} not found. Run ./install.sh, or copy config.example.ini to config.ini and edit it.")
    parser = configparser.ConfigParser()
    parser.read(path)
    if "openweather" not in parser:
        raise StationError(f"{path.name} has no [openweather] section. Compare it with config.example.ini.")
    section = parser["openweather"]

    api_key = section.get("api_key", "").strip()
    if not api_key or api_key.startswith("YOUR_"):
        raise StationError(f"Set api_key in {path.name}.")
    try:
        lat, lon = float(section["latitude"]), float(section["longitude"])
    except (KeyError, ValueError):
        raise StationError(f"Set latitude and longitude in {path.name} as decimal numbers, e.g. 51.51 and -0.13.")
    units = section.get("units", "imperial").strip().lower()
    if units not in UNIT_SYMBOLS:
        raise StationError(f"units in {path.name} must be one of: {', '.join(UNIT_SYMBOLS)}.")
    return {"api_key": api_key, "lat": lat, "lon": lon, "units": units}


def fetch_weather(cfg):
    params = {
        "lat": cfg["lat"],
        "lon": cfg["lon"],
        "units": cfg["units"],
        "exclude": "minutely,hourly,alerts",
        "appid": cfg["api_key"],
    }
    # Error messages deliberately omit the request URL, which contains the API key
    try:
        resp = requests.get(ONE_CALL_URL, params=params, timeout=30)
    except requests.RequestException as e:
        raise StationError(f"Could not reach OpenWeather ({type(e).__name__}). Check the network connection.") from None
    if resp.status_code == 401:
        raise StationError(
            "OpenWeather rejected the API key (401). One Call API 3.0 needs its own subscription on your "
            "account, and new keys can take a couple of hours to activate."
        )
    if resp.status_code != 200:
        raise StationError(f"OpenWeather returned HTTP {resp.status_code}.")
    return resp.json()


def fit_line(draw, text, font, max_width, force_ellipsis=False):
    """Trim text with an ellipsis until it fits max_width."""
    if not force_ellipsis and draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(text + "…", font=font) > max_width:
        text = text[:-1].rstrip()
    return text + "…"


def draw_wrapped(draw, text, xy, font, max_width, max_lines):
    """Word-wrap text into at most max_lines lines, ending in an ellipsis if it doesn't all fit."""
    lines, current = [], ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and draw.textlength(candidate, font=font) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)

    truncated = len(lines) > max_lines
    lines = lines[:max_lines]
    x, y = xy
    for i, line in enumerate(lines):
        is_last = i == len(lines) - 1
        draw.text((x, y), fit_line(draw, line, font, max_width, force_ellipsis=truncated and is_last), font=font, fill=0)
        y += font.size + 2


def render(data, units, updated_at):
    """Draw the forecast as a 1-bit landscape image."""
    font_title = ImageFont.truetype(str(FONT_BOLD), 25)
    font_text = ImageFont.truetype(str(FONT_REGULAR), 21)
    font_small = ImageFont.truetype(str(FONT_REGULAR), 12)

    image = Image.new("1", (WIDTH, HEIGHT), 255)  # 255 = white
    draw = ImageDraw.Draw(image)
    symbol = UNIT_SYMBOLS[units]
    current, daily = data["current"], data["daily"]

    def temp(value):
        return f"{round(value)}{symbol}"

    def conditions(day):
        return day["weather"][0]["description"].capitalize()

    # Top row: current temperature, then today's range and conditions
    draw.text((0, 0), "Now", font=font_title, fill=0)
    draw.text((0, 30), temp(current["temp"]), font=font_text, fill=0)

    draw.text((100, 0), "Today", font=font_title, fill=0)
    today_high = f"High: {temp(daily[0]['temp']['max'])}"
    draw.text((100, 30), today_high, font=font_text, fill=0)
    # Low normally sits at x=225 but shifts right when a triple-digit high needs the room
    low_x = max(225, 100 + draw.textlength(today_high, font=font_text) + 12)
    draw.text((low_x, 30), f"Low: {temp(daily[0]['temp']['min'])}", font=font_text, fill=0)
    draw_wrapped(draw, conditions(daily[0]), (100, 60), font_text, max_width=WIDTH - 100, max_lines=1)

    # Bottom row: the next two days
    for x, label, day in ((0, "Tomorrow", daily[1]), (180, "Next Day", daily[2])):
        draw.text((x, 95), label, font=font_title, fill=0)
        draw.text((x, 125), f"High: {temp(day['temp']['max'])}", font=font_text, fill=0)
        draw.text((x, 150), f"Low: {temp(day['temp']['min'])}", font=font_text, fill=0)
        draw_wrapped(draw, conditions(day), (x, 175), font_text, max_width=170, max_lines=2)

    # Section dividers
    draw.line((0, 90, WIDTH, 90), fill=0, width=2)
    draw.line((85, 0, 85, 90), fill=0, width=2)
    draw.line((175, 90, 175, 220), fill=0, width=2)

    stamp = f"Last updated: {updated_at:%-m/%-d/%Y %-I:%M %p}"
    draw.text(((WIDTH - draw.textlength(stamp, font=font_small)) / 2, 224), stamp, font=font_small, fill=0)
    return image


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


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--preview", metavar="PNG", help="save the rendered screen to an image instead of the display")
    parser.add_argument("--demo", action="store_true", help="use sample_data.json instead of calling OpenWeather")
    parser.add_argument("--deep-clean", action="store_true", help="cycle the panel black and white before drawing")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Cron can start a run while a slow one is still refreshing the panel; never drive it twice at once
    lock = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log.warning("Another update is still running; skipping this one.")
        return 0

    # Fetch and render before touching the panel, so a failed fetch leaves the last good forecast on screen
    try:
        if args.demo:
            data, units = json.loads(SAMPLE_PATH.read_text()), "imperial"
        else:
            cfg = load_config(CONFIG_PATH)
            data, units = fetch_weather(cfg), cfg["units"]
        image = render(data, units, datetime.now())
    except StationError as e:
        log.error("%s", e)
        return 1
    except (KeyError, IndexError, TypeError) as e:
        log.error("Unexpected response format from OpenWeather (missing %s).", e)
        return 1

    if args.preview:
        image.save(args.preview)
        log.info("Saved preview to %s", args.preview)
        return 0

    show_on_display(image, deep_clean=args.deep_clean)
    log.info("Display updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
