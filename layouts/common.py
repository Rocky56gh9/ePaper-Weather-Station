"""Pieces every layout shares: fonts, weather icons, formatting, the drawing canvas, and the
forecast resolved against the current time."""
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_DIR = Path(__file__).resolve().parent.parent / "fonts"
WIND_UNITS = {"imperial": "mph", "metric": "m/s"}

# Weather Icons font codepoints (https://erikflowers.github.io/weather-icons/)
GLYPHS = {
    "day_clear": "", "night_clear": "",
    "day_partly": "", "night_partly": "",
    "cloudy": "", "showers": "", "rain": "",
    "storm": "", "snow": "", "fog": "",
    "raindrop": "", "wind": "", "sunrise": "",
    "sunset": "", "humidity": "", "barometer": "",
    "thermometer": "",
}
# 28 moon glyphs from new (0) through waxing, full (14), and waning, matching One Call's moon_phase 0..1
MOON_FIRST = 0xF095


@lru_cache(maxsize=None)
def font(kind, size):
    files = {"bold": "DejaVuSans-Bold.ttf", "regular": "DejaVuSans.ttf", "icons": "weathericons-regular.ttf"}
    return ImageFont.truetype(str(FONT_DIR / files[kind]), size)


def condition_kind(condition_id, night=False):
    """Map an OpenWeather condition code (https://openweathermap.org/weather-conditions) to an icon name."""
    if condition_id < 300:
        return "storm"
    if condition_id < 400:
        return "showers"
    if condition_id < 600:
        return "rain"
    if condition_id < 700:
        return "snow"
    if condition_id < 800:
        return "fog"
    if condition_id == 800:
        return "night_clear" if night else "day_clear"
    if condition_id <= 802:
        return "night_partly" if night else "day_partly"
    return "cloudy"


def weather_glyph(condition_id, night=False):
    return GLYPHS[condition_kind(condition_id, night)]


def moon_glyph(phase):
    return chr(MOON_FIRST + round(phase * 28) % 28)


def moon_name(phase):
    """One Call moon_phase: 0 and 1 are new moon, 0.25 first quarter, 0.5 full, 0.75 last quarter."""
    for limit, name in ((0.03, "New moon"), (0.22, "Waxing crescent"), (0.28, "First quarter"),
                        (0.47, "Waxing gibbous"), (0.53, "Full moon"), (0.72, "Waning gibbous"),
                        (0.78, "Last quarter"), (0.97, "Waning crescent")):
        if phase < limit:
            return name
    return "New moon"


def compass(degrees):
    points = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return points[round(degrees / 22.5) % 16]


def deg(value):
    return f"{round(value)}°"


def clock(dt):
    return dt.strftime("%-I:%M %p")


class Canvas:
    """A palette image plus drawing helpers that take coordinates in design units.

    palette lists the panel's inks as RGB in the panel's own index order, so the image can go to the
    driver without conversion. Positions are written for design_width and scaled to the real width.
    """

    def __init__(self, width, height, palette, background, design_width):
        self.width, self.height = width, height
        self.scale = width / design_width
        self.image = Image.new("P", (width, height), background)
        flat = [value for rgb in palette for value in rgb]
        self.image.putpalette(flat + [0, 0, 0] * (256 - len(palette)))
        self.draw = ImageDraw.Draw(self.image)

    def px(self, value):
        return round(value * self.scale)

    def font(self, kind, size):
        return font(kind, self.px(size))

    def text_width(self, text, kind, size):
        return self.draw.textlength(text, font=self.font(kind, size))

    def text(self, xy, text, kind, size, fill):
        """Draw text at a position in design units."""
        self.draw.text((self.px(xy[0]), self.px(xy[1])), text, font=self.font(kind, size), fill=fill)

    def text_at(self, xy, text, kind, size, fill):
        """Draw text at a position already in screen pixels."""
        self.draw.text(xy, text, font=self.font(kind, size), fill=fill)

    def centered(self, text, center_x, y, kind, size, fill):
        """center_x in screen pixels, y in design units."""
        self.text_at((center_x - self.text_width(text, kind, size) / 2, self.px(y)), text, kind, size, fill)

    def fit(self, text, kind, size, max_width, force_ellipsis=False):
        """Trim text with an ellipsis until it fits max_width screen pixels."""
        if not force_ellipsis and self.text_width(text, kind, size) <= max_width:
            return text
        while text and self.text_width(text + "…", kind, size) > max_width:
            text = text[:-1].rstrip()
        return text + "…"


class Forecast:
    """The slices of a One Call response a screen needs, resolved against the current time.

    Selecting by timestamp instead of list position keeps a cached (offline) forecast honest:
    the hourly strip starts at the current hour and "Tomorrow" stays tomorrow.
    """

    def __init__(self, data, now, hours=12, days=3):
        self.tz = timezone(timedelta(seconds=data["timezone_offset"]))
        self.now = now.astimezone(self.tz)
        self.current = data["current"]
        self.alerts = data.get("alerts", [])

        today = self.now.date()
        daily = data["daily"]
        self.today = next((d for d in daily if self.local(d["dt"]).date() == today), daily[0])
        self.next_days = [d for d in daily if self.local(d["dt"]).date() > today][:days]

        hour_start = self.now.timestamp() - 3600
        self.hours = [h for h in data["hourly"] if h["dt"] > hour_start][:hours]

    def local(self, ts):
        return datetime.fromtimestamp(ts, self.tz)

    @property
    def is_night(self):
        return not (self.today["sunrise"] <= self.now.timestamp() < self.today["sunset"])

    def active_alerts(self):
        ts = self.now.timestamp()
        return [a for a in self.alerts if a.get("start", 0) <= ts < a.get("end", ts + 1)]
