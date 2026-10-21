"""Draws the station's screen from a One Call API 3.0 response.

Positions are written for the original 360x240 design and scaled to the target screen's width;
any extra height goes to the 12-hour chart. Screen regions (landscape):

    +-------------------+----------------------+
    | icon  64°         |  Thu    Fri    Sat   |  Now / Tonight      |  next three days
    |       Feels 62°   |  icon   icon   icon  |
    | ↑64°  ↓45°        |  67°    57°    59°   |
    | Clear sky         |  44°    42°    38°   |
    | 💧80%  🌬24mph    |         💧35%        |
    +-------------------+----------------------+
    |  next 12 hours: temperature line over rain-chance bars    |
    +-----------------------------------------------------------+
    | sunrise-sunset or "colder tomorrow"    Updated 4:19 PM    |  or an alert/offline banner
    +-----------------------------------------------------------+

Images use a three-entry palette (white, black, accent). On black-and-white screens the
accent is drawn as black; on Inky red or yellow screens it marks alerts, rain, and big changes.
"""
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

DESIGN_WIDTH = 360
FONT_DIR = Path(__file__).resolve().parent / "fonts"
WIND_UNITS = {"imperial": "mph", "metric": "m/s"}

# Palette indices; they match Pimoroni Inky's WHITE, BLACK, and RED/YELLOW
WHITE, BLACK, ACCENT = 0, 1, 2
ACCENT_RGB = {"red": (220, 0, 0), "yellow": (230, 190, 0)}

# Weather Icons font codepoints (https://erikflowers.github.io/weather-icons/)
GLYPHS = {
    "day_clear": "", "night_clear": "",
    "day_partly": "", "night_partly": "",
    "cloudy": "", "showers": "", "rain": "",
    "storm": "", "snow": "", "fog": "",
    "raindrop": "", "wind": "", "sunrise": "",
}


@lru_cache(maxsize=None)
def font(kind, size):
    files = {"bold": "DejaVuSans-Bold.ttf", "regular": "DejaVuSans.ttf", "icons": "weathericons-regular.ttf"}
    return ImageFont.truetype(str(FONT_DIR / files[kind]), size)


def weather_glyph(condition_id, night=False):
    """Map an OpenWeather condition code (https://openweathermap.org/weather-conditions) to an icon."""
    if condition_id < 300:
        return GLYPHS["storm"]
    if condition_id < 400:
        return GLYPHS["showers"]
    if condition_id < 600:
        return GLYPHS["rain"]
    if condition_id < 700:
        return GLYPHS["snow"]
    if condition_id < 800:
        return GLYPHS["fog"]
    if condition_id == 800:
        return GLYPHS["night_clear" if night else "day_clear"]
    if condition_id <= 802:
        return GLYPHS["night_partly" if night else "day_partly"]
    return GLYPHS["cloudy"]


def deg(value):
    return f"{round(value)}°"


def clock(dt):
    return dt.strftime("%-I:%M %p")


class Canvas:
    """A palette image plus drawing helpers that take coordinates in 360-wide design units."""

    def __init__(self, width, height, accent=None):
        self.width, self.height = width, height
        self.scale = width / DESIGN_WIDTH
        self.accent = ACCENT if accent else BLACK
        self.image = Image.new("P", (width, height), WHITE)
        self.image.putpalette([255, 255, 255, 0, 0, 0, *ACCENT_RGB.get(accent, (0, 0, 0))] + [0, 0, 0] * 253)
        self.draw = ImageDraw.Draw(self.image)

        self.left_panel_right = self.px(172)
        self.top_row_bottom = self.px(140)
        self.footer_top = height - self.px(24)

    def px(self, value):
        return round(value * self.scale)

    def font(self, kind, size):
        return font(kind, self.px(size))

    def text_width(self, text, kind, size):
        return self.draw.textlength(text, font=self.font(kind, size))

    def text(self, xy, text, kind, size, fill=BLACK):
        """Draw text at a position in design units."""
        self.draw.text((self.px(xy[0]), self.px(xy[1])), text, font=self.font(kind, size), fill=fill)

    def text_at(self, xy, text, kind, size, fill=BLACK):
        """Draw text at a position already in screen pixels."""
        self.draw.text(xy, text, font=self.font(kind, size), fill=fill)

    def centered(self, text, center_x, y, kind, size, fill=BLACK):
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
    """The slices of a One Call response the screen needs, resolved against the current time.

    Selecting by timestamp instead of list position keeps a cached (offline) forecast honest:
    the hourly strip starts at the current hour and "Tomorrow" stays tomorrow.
    """

    def __init__(self, data, now):
        self.tz = timezone(timedelta(seconds=data["timezone_offset"]))
        self.now = now.astimezone(self.tz)
        self.current = data["current"]
        self.alerts = data.get("alerts", [])

        today = self.now.date()
        daily = data["daily"]
        self.today = next((d for d in daily if self.local(d["dt"]).date() == today), daily[0])
        self.next_days = [d for d in daily if self.local(d["dt"]).date() > today][:3]

        hour_start = self.now.timestamp() - 3600
        self.hours = [h for h in data["hourly"] if h["dt"] > hour_start][:12]

    def local(self, ts):
        return datetime.fromtimestamp(ts, self.tz)

    @property
    def is_night(self):
        return not (self.today["sunrise"] <= self.now.timestamp() < self.today["sunset"])

    def active_alerts(self):
        ts = self.now.timestamp()
        return [a for a in self.alerts if a.get("start", 0) <= ts < a.get("end", ts + 1)]


def notable_conditions(fc, units, thresholds, evening):
    """Rain, wind, and UV callouts, included only when they cross the configured thresholds."""
    notes = []
    rain_chance = max((h.get("pop", 0) for h in fc.hours), default=0) if evening else fc.today.get("pop", 0)
    if rain_chance >= 0.2:
        notes.append((GLYPHS["raindrop"], f"{round(rain_chance * 100)}%"))

    wind, gusts = fc.current.get("wind_speed", 0), fc.current.get("wind_gust", 0)
    if gusts >= thresholds["gusts"]:
        notes.append((GLYPHS["wind"], f"gusts {round(gusts)}"))
    elif wind >= thresholds["wind"]:
        notes.append((GLYPHS["wind"], f"{round(wind)}{WIND_UNITS[units]}"))

    if not evening and fc.today.get("uvi", 0) >= thresholds["uv_index"]:
        notes.append((None, f"UV {round(fc.today['uvi'])}"))
    return notes


def draw_now_panel(c, fc, units, thresholds, evening):
    current = fc.current
    panel_right = c.left_panel_right

    # Icons vary in width (sun vs. cloud-and-sun), so fit each into a fixed box. The gap before the
    # temperature matters: a sun ray touching "48°" reads as "-48°".
    glyph, icon_size = weather_glyph(current["weather"][0]["id"], fc.is_night), 54
    while c.text_width(glyph, "icons", icon_size) > c.px(68):
        icon_size -= 2
    c.text((4, (54 - icon_size) / 2), glyph, "icons", icon_size)

    # Shrink the big temperature until it fits beside the icon (triple digits, negatives)
    temp_x, temp_text, size = 86, deg(current["temp"]), 44
    while size > 28 and c.text_width(temp_text, "bold", size) > panel_right - c.px(4 + temp_x):
        size -= 2
    c.text((temp_x, 4 + (44 - size) / 2), temp_text, "bold", size)
    c.text((temp_x + 2, 54), f"Feels {deg(current['feels_like'])}", "regular", 14)

    if evening:
        low = min((h["temp"] for h in fc.hours), default=fc.today["temp"]["min"])
        summary = f"Tonight ↓{deg(low)}"
    else:
        summary = f"↑{deg(fc.today['temp']['max'])}  ↓{deg(fc.today['temp']['min'])}"
    c.text((6, 78), summary, "bold", 17)

    description = current["weather"][0]["description"].capitalize()
    c.text((6, 100), c.fit(description, "regular", 15, panel_right - c.px(12)), "regular", 15)

    x = c.px(6)
    for glyph, text in notable_conditions(fc, units, thresholds, evening):
        width = (c.px(18) if glyph else 0) + c.text_width(text, "bold", 14)
        if x + width > panel_right - c.px(4):
            break
        if glyph:
            c.text_at((x, c.px(118)), glyph, "icons", 16, fill=c.accent if glyph == GLYPHS["raindrop"] else BLACK)
            x += c.px(18)
        c.text_at((x, c.px(120)), text, "bold", 14)
        x += c.text_width(text, "bold", 14) + c.px(10)


def draw_next_days(c, fc):
    column = (c.width - c.left_panel_right) / 3
    for i, day in enumerate(fc.next_days):
        cx = c.left_panel_right + column * i + column / 2
        c.centered(fc.local(day["dt"]).strftime("%a"), cx, 2, "bold", 15)
        c.centered(weather_glyph(day["weather"][0]["id"]), cx, 18, "icons", 30)
        c.centered(deg(day["temp"]["max"]), cx, 72, "bold", 17)
        c.centered(deg(day["temp"]["min"]), cx, 93, "regular", 15)
        if day.get("pop", 0) >= 0.1:
            pct = f"{round(day['pop'] * 100)}%"
            left = cx - (c.px(14) + c.text_width(pct, "regular", 13)) / 2
            c.text_at((left, c.px(116)), GLYPHS["raindrop"], "icons", 14, fill=c.accent)
            c.text_at((left + c.px(14), c.px(118)), pct, "regular", 13)


def draw_hourly(c, fc):
    """Temperature line over rain-chance bars for the next 12 hours."""
    hours = fc.hours
    top, bottom = c.top_row_bottom + c.px(12), c.footer_top - c.px(16)
    left, right = c.px(8), c.width - c.px(8)
    if len(hours) < 2:
        c.centered("No hourly forecast available", c.width / 2, top / c.scale + 18, "regular", 13)
        return
    step = (right - left) / len(hours)
    temps = [h["temp"] for h in hours]
    t_min, t_max = min(temps), max(temps)
    span = max(t_max - t_min, 4)  # keep a flat day from looking dramatic

    points = []
    for i, hour in enumerate(hours):
        x0 = left + i * step
        pop = hour.get("pop", 0)
        if pop >= 0.05:
            bar = (int(x0 + c.px(3)), int(bottom - (bottom - top) * pop), int(x0 + step - c.px(3)), bottom - 1)
            if c.accent == ACCENT:
                c.draw.rectangle(bar, fill=ACCENT)
            else:
                # A checkerboard reads as gray on a 1-bit panel, so the temperature line stays visible on top
                for y in range(bar[1], bar[3] + 1):
                    for x in range(bar[0], bar[2]):
                        if (x + y) % 2 == 0:
                            c.image.putpixel((x, y), BLACK)
        y = bottom - c.px(6) - (hour["temp"] - t_min) / span * (bottom - top - c.px(14))
        points.append((x0 + step / 2, y))
        if i % 3 == 0:
            label = fc.local(hour["dt"]).strftime("%-I%p").lower().rstrip("m")
            c.centered(label, x0 + step / 2, (bottom + c.px(2)) / c.scale, "regular", 11)
    c.draw.line(points, fill=BLACK, width=c.px(2))
    c.draw.line((left, bottom, right, bottom), fill=BLACK, width=1)

    # Label the high and low just above the line; the low sits on the axis, so below would hit the hour labels
    labels = [t_max] if t_max == t_min else [t_max, t_min]
    for value in labels:
        x, y = points[temps.index(value)]
        c.text_at((min(max(x - c.px(10), 0), c.width - c.px(30)), y - c.px(15)), deg(value), "bold", 11)


def draw_banner(c, text, suffix="", fill=BLACK):
    """White-on-color footer. When space runs out, text is shortened and suffix is always kept whole."""
    c.draw.rectangle((0, c.footer_top, c.width, c.height), fill=fill)
    room = c.width - c.px(12) - c.text_width(suffix, "bold", 13)
    c.centered(c.fit(text, "bold", 13, room) + suffix, c.width / 2, c.footer_top / c.scale + 5, "bold", 13, fill=WHITE)


def draw_footer(c, fc, thresholds, updated_at, offline_since):
    if offline_since:
        since = fc.local(offline_since.timestamp())
        when = clock(since) if since.date() == fc.now.date() else since.strftime("%a ") + clock(since)
        draw_banner(c, f"OFFLINE · forecast from {when}")
        return

    alerts = fc.active_alerts()
    if alerts:
        first = alerts[0]
        suffix = f" until {fc.local(first['end']).strftime('%-I %p')}"
        if len(alerts) > 1:
            suffix += f" (+{len(alerts) - 1})"
        draw_banner(c, f"⚠ {first['event']}", suffix, fill=c.accent)
        return

    y = c.footer_top / c.scale + 5
    swing = fc.next_days[0]["temp"]["max"] - fc.today["temp"]["max"] if fc.next_days else 0
    if abs(swing) >= thresholds["temp_swing"]:
        word = "warmer" if swing > 0 else "colder"
        c.text((6, y - 1), f"{'↑' if swing > 0 else '↓'}{deg(abs(swing))} {word} tomorrow", "bold", 13, fill=c.accent)
    else:
        sunrise, sunset = fc.local(fc.today["sunrise"]), fc.local(fc.today["sunset"])
        c.text((6, y - 5), GLYPHS["sunrise"], "icons", 18)
        c.text((30, y), f"{sunrise:%-I:%M}–{sunset:%-I:%M}", "regular", 12)

    stamp = f"Updated {clock(fc.local(updated_at.timestamp()))}"
    c.text_at((c.width - c.px(6) - c.text_width(stamp, "regular", 12), c.px(y)), stamp, "regular", 12)


def render(data, units, thresholds, now, size=(360, 240), accent=None, evening_starts=18, offline_since=None):
    """Draw the full screen as a palette image (white, black, accent).

    now and offline_since are timezone-aware datetimes. offline_since marks the data as a cached
    forecast and replaces the footer with an offline banner. accent is "red", "yellow", or None.
    """
    fc = Forecast(data, now)
    evening = fc.now.hour >= evening_starts

    c = Canvas(*size, accent=accent)
    draw_now_panel(c, fc, units, thresholds, evening)
    draw_next_days(c, fc)
    c.draw.line((c.left_panel_right, 0, c.left_panel_right, c.top_row_bottom), fill=BLACK, width=c.px(2))
    c.draw.line((0, c.top_row_bottom, c.width, c.top_row_bottom), fill=BLACK, width=c.px(2))
    draw_hourly(c, fc)
    draw_footer(c, fc, thresholds, updated_at=now, offline_since=offline_since)
    return c.image
