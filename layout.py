"""Draws the station's screen: a 360x240 1-bit image built from a One Call API 3.0 response.

Screen regions (landscape):

    +-------------------+----------------------+
    | icon  64°         |  Thu    Fri    Sat   |  Now / Tonight      |  next three days
    |       Feels 62°   |  icon   icon   icon  |
    | ↑64°  ↓45°        |  67°    57°    59°   |
    | Clear sky         |  44°    42°    38°   |
    | 💧80%  🌬24mph    |         💧35%        |
    +-------------------+----------------------+ y=140
    |  next 12 hours: temperature line over rain-chance bars    |
    +-----------------------------------------------------------+ y=216
    | sunrise-sunset or "colder tomorrow"    Updated 4:19 PM    |  or an alert/offline banner
    +-----------------------------------------------------------+
"""
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 360, 240
FONT_DIR = Path(__file__).resolve().parent / "fonts"
WIND_UNITS = {"imperial": "mph", "metric": "m/s"}

LEFT_PANEL_RIGHT = 172
TOP_ROW_BOTTOM = 140
FOOTER_TOP = 216

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


def fit_line(draw, text, fnt, max_width, force_ellipsis=False):
    """Trim text with an ellipsis until it fits max_width."""
    if not force_ellipsis and draw.textlength(text, font=fnt) <= max_width:
        return text
    while text and draw.textlength(text + "…", font=fnt) > max_width:
        text = text[:-1].rstrip()
    return text + "…"


def draw_centered(draw, text, center_x, y, fnt, fill=0):
    draw.text((center_x - draw.textlength(text, font=fnt) / 2, y), text, font=fnt, fill=fill)


def deg(value):
    return f"{round(value)}°"


def clock(dt):
    return dt.strftime("%-I:%M %p")


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


def draw_now_panel(draw, fc, units, thresholds, evening):
    current = fc.current
    # Icons vary in width (sun vs. cloud-and-sun), so fit each into a fixed box. The gap before the
    # temperature matters: a sun ray touching "48°" reads as "-48°".
    glyph, icon_size = weather_glyph(current["weather"][0]["id"], fc.is_night), 54
    while draw.textlength(glyph, font=font("icons", icon_size)) > 68:
        icon_size -= 2
    draw.text((4, (54 - icon_size) // 2), glyph, font=font("icons", icon_size), fill=0)

    # Shrink the big temperature until it fits beside the icon (triple digits, negatives)
    temp_x, temp_text, size = 86, deg(current["temp"]), 44
    while size > 28 and draw.textlength(temp_text, font=font("bold", size)) > LEFT_PANEL_RIGHT - 4 - temp_x:
        size -= 2
    draw.text((temp_x, 4 + (44 - size) // 2), temp_text, font=font("bold", size), fill=0)
    draw.text((temp_x + 2, 54), f"Feels {deg(current['feels_like'])}", font=font("regular", 14), fill=0)

    if evening:
        low = min((h["temp"] for h in fc.hours), default=fc.today["temp"]["min"])
        summary = f"Tonight ↓{deg(low)}"
    else:
        summary = f"↑{deg(fc.today['temp']['max'])}  ↓{deg(fc.today['temp']['min'])}"
    draw.text((6, 78), summary, font=font("bold", 17), fill=0)

    description = current["weather"][0]["description"].capitalize()
    draw.text((6, 100), fit_line(draw, description, font("regular", 15), LEFT_PANEL_RIGHT - 12), font=font("regular", 15), fill=0)

    x = 6
    for glyph, text in notable_conditions(fc, units, thresholds, evening):
        width = (18 if glyph else 0) + draw.textlength(text, font=font("bold", 14))
        if x + width > LEFT_PANEL_RIGHT - 4:
            break
        if glyph:
            draw.text((x, 118), glyph, font=font("icons", 16), fill=0)
            x += 18
        draw.text((x, 120), text, font=font("bold", 14), fill=0)
        x += draw.textlength(text, font=font("bold", 14)) + 10


def draw_next_days(draw, fc):
    column = (WIDTH - LEFT_PANEL_RIGHT) / 3
    for i, day in enumerate(fc.next_days):
        cx = LEFT_PANEL_RIGHT + column * i + column / 2
        draw_centered(draw, fc.local(day["dt"]).strftime("%a"), cx, 2, font("bold", 15))
        draw_centered(draw, weather_glyph(day["weather"][0]["id"]), cx, 18, font("icons", 30))
        draw_centered(draw, deg(day["temp"]["max"]), cx, 72, font("bold", 17))
        draw_centered(draw, deg(day["temp"]["min"]), cx, 93, font("regular", 15))
        if day.get("pop", 0) >= 0.1:
            pct = f"{round(day['pop'] * 100)}%"
            width = 14 + draw.textlength(pct, font=font("regular", 13))
            draw.text((cx - width / 2, 116), GLYPHS["raindrop"], font=font("icons", 14), fill=0)
            draw.text((cx - width / 2 + 14, 118), pct, font=font("regular", 13), fill=0)


def draw_hourly(image, draw, fc):
    """Temperature line over dithered rain-chance bars for the next 12 hours."""
    hours = fc.hours
    if len(hours) < 2:
        draw_centered(draw, "No hourly forecast available", WIDTH / 2, 170, font("regular", 13))
        return
    top, bottom, left, right = 152, 200, 8, WIDTH - 8
    step = (right - left) / len(hours)
    temps = [h["temp"] for h in hours]
    t_min, t_max = min(temps), max(temps)
    span = max(t_max - t_min, 4)  # keep a flat day from looking dramatic

    points = []
    for i, hour in enumerate(hours):
        x0 = left + i * step
        pop = hour.get("pop", 0)
        if pop >= 0.05:
            # A checkerboard reads as gray on a 1-bit panel, so the temperature line stays visible on top
            bar_top = int(bottom - (bottom - top) * pop)
            for y in range(bar_top, bottom):
                for x in range(int(x0 + 3), int(x0 + step - 3)):
                    if (x + y) % 2 == 0:
                        image.putpixel((x, y), 0)
        y = bottom - 6 - (hour["temp"] - t_min) / span * (bottom - top - 14)
        points.append((x0 + step / 2, y))
        if i % 3 == 0:
            label = fc.local(hour["dt"]).strftime("%-I%p").lower().rstrip("m")
            draw_centered(draw, label, x0 + step / 2, bottom + 2, font("regular", 11))
    draw.line(points, fill=0, width=2)
    draw.line((left, bottom, right, bottom), fill=0, width=1)

    # Label the high and low just above the line; the low sits on the axis, so below would hit the hour labels
    labels = [t_max] if t_max == t_min else [t_max, t_min]
    for value in labels:
        x, y = points[temps.index(value)]
        draw.text((min(max(x - 10, 0), WIDTH - 30), y - 15), deg(value), font=font("bold", 11), fill=0)


def draw_banner(draw, text, suffix=""):
    """White-on-black footer. When space runs out, text is shortened and suffix is always kept whole."""
    draw.rectangle((0, FOOTER_TOP, WIDTH, HEIGHT), fill=0)
    fnt = font("bold", 13)
    room = WIDTH - 12 - draw.textlength(suffix, font=fnt)
    draw_centered(draw, fit_line(draw, text, fnt, room) + suffix, WIDTH / 2, FOOTER_TOP + 5, fnt, fill=255)


def draw_footer(draw, fc, thresholds, updated_at, offline_since):
    if offline_since:
        since = fc.local(offline_since.timestamp())
        when = clock(since) if since.date() == fc.now.date() else since.strftime("%a ") + clock(since)
        draw_banner(draw, f"OFFLINE · forecast from {when}")
        return

    alerts = fc.active_alerts()
    if alerts:
        first = alerts[0]
        suffix = f" until {fc.local(first['end']).strftime('%-I %p')}"
        if len(alerts) > 1:
            suffix += f" (+{len(alerts) - 1})"
        draw_banner(draw, f"⚠ {first['event']}", suffix)
        return

    y = FOOTER_TOP + 5
    swing = fc.next_days[0]["temp"]["max"] - fc.today["temp"]["max"] if fc.next_days else 0
    if abs(swing) >= thresholds["temp_swing"]:
        word = "warmer" if swing > 0 else "colder"
        draw.text((6, y - 1), f"{'↑' if swing > 0 else '↓'}{deg(abs(swing))} {word} tomorrow", font=font("bold", 13), fill=0)
    else:
        sunrise, sunset = fc.local(fc.today["sunrise"]), fc.local(fc.today["sunset"])
        draw.text((6, y - 5), GLYPHS["sunrise"], font=font("icons", 18), fill=0)
        draw.text((30, y), f"{sunrise:%-I:%M}–{sunset:%-I:%M}", font=font("regular", 12), fill=0)

    stamp = f"Updated {clock(fc.local(updated_at.timestamp()))}"
    draw.text((WIDTH - 6 - draw.textlength(stamp, font=font("regular", 12)), y), stamp, font=font("regular", 12), fill=0)


def render(data, units, thresholds, now, evening_starts=18, offline_since=None):
    """Draw the full screen.

    now and offline_since are timezone-aware datetimes. offline_since marks the data as a cached
    forecast and replaces the footer with an offline banner.
    """
    fc = Forecast(data, now)
    evening = fc.now.hour >= evening_starts

    image = Image.new("1", (WIDTH, HEIGHT), 255)  # 255 = white
    draw = ImageDraw.Draw(image)
    draw_now_panel(draw, fc, units, thresholds, evening)
    draw_next_days(draw, fc)
    draw.line((LEFT_PANEL_RIGHT, 0, LEFT_PANEL_RIGHT, TOP_ROW_BOTTOM), fill=0, width=2)
    draw.line((0, TOP_ROW_BOTTOM, WIDTH, TOP_ROW_BOTTOM), fill=0, width=2)
    draw_hourly(image, draw, fc)
    draw_footer(draw, fc, thresholds, updated_at=now, offline_since=offline_since)
    return image
