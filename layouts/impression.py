"""The Inky Impression 5.7" layout (600x448, 7 inks), from a One Call API 3.0 response.

    +--------------------------+-------------------------------+
    | icon  48°                | Rain today      Wind          |  now, plus a details grid
    |       Feels 45°          | 70% · 0.17 in   W 9 mph       |
    | Few clouds               | UV index        Humidity      |
    | ↑61°  ↓45°               | (4) Moderate    71%           |
    |                          | Pressure        Dew point     |
    |                          | Sun             Moon          |
    +--------------------------+-------------------------------+
    |  next 24 hours: temperature line over rain-chance bars   |
    +----------------------------------------------------------+
    |  Thu   Fri   Sat   Sun   Mon   Tue   Wed                 |  next seven days
    +----------------------------------------------------------+
    | today's summary or "colder tomorrow"   Updated 7:30 AM   |  or an alert/offline banner
    +----------------------------------------------------------+

Color carries meaning, never decoration: blue is rain and cold, orange is sun and warmth, red is
heat and government alerts, and the UV index uses the standard green-yellow-orange-red scale.
Every color is one of the panel's pure inks, so nothing is dithered.
"""
from .common import (GLYPHS, WIND_UNITS, Canvas, Forecast, clock, compass, condition_kind, deg,
                     moon_glyph, moon_name, weather_glyph)

DESIGN_WIDTH = 600

# The panel's ink order, as used by Pimoroni's inky library for the Impression
BLACK, WHITE, GREEN, BLUE, RED, YELLOW, ORANGE = range(7)
# Approximate on-panel colors, for previews; the panel itself only sees the indices
PALETTE = [(25, 25, 30), (255, 255, 255), (35, 125, 65), (40, 70, 165), (205, 45, 45), (235, 205, 45), (230, 120, 40)]

# Temperatures at or below cold are blue; at or above warm, orange; at or above hot, red
TEMP_BANDS = {"imperial": (40, 80, 90), "metric": (4, 27, 32)}
# Dew point comfort, the usual US National Weather Service wording
DEW_POINT_BANDS = {"imperial": ((50, "dry"), (60, "comfortable"), (65, "sticky"), (70, "humid")),
                   "metric": ((10, "dry"), (16, "comfortable"), (18, "sticky"), (21, "humid"))}
ICON_INKS = {"day_clear": ORANGE, "day_partly": ORANGE, "rain": BLUE, "showers": BLUE, "storm": BLUE, "snow": BLUE}

TOP_BOTTOM = 172      # end of the now panel and details grid
CHART_BOTTOM = 300    # end of the 24-hour chart, including its hour labels
FOOTER_HEIGHT = 28


def temp_ink(value, units):
    cold, warm, hot = TEMP_BANDS[units]
    if value <= cold:
        return BLUE
    if value >= hot:
        return RED
    if value >= warm:
        return ORANGE
    return BLACK


def uv_style(uvi):
    """(pill fill, text ink, word) on the WHO UV index scale."""
    if uvi < 3:
        return GREEN, WHITE, "Low"
    if uvi < 6:
        return YELLOW, BLACK, "Moderate"
    if uvi < 8:
        return ORANGE, BLACK, "High"
    if uvi < 11:
        return RED, WHITE, "Very high"
    return RED, WHITE, "Extreme"


def dew_point_word(value, units):
    for limit, word in DEW_POINT_BANDS[units]:
        if value < limit:
            return word
    return "oppressive"


def rain_amount(mm, units):
    """One Call reports rain and snow in mm in both unit systems."""
    if units == "imperial":
        inches = mm / 25.4
        return f"{inches:.2f} in" if inches < 1 else f"{inches:.1f} in"
    return f"{mm:.1f} mm" if mm < 10 else f"{round(mm)} mm"


def pressure_text(hpa, units):
    return f"{hpa * 0.02953:.2f} in" if units == "imperial" else f"{round(hpa)} hPa"


def pressure_trend(fc):
    """Forecast change over the next three hours: rising, falling, or steady (under 1 hPa)."""
    ahead = [h["pressure"] for h in fc.hours[3:4] if "pressure" in h]
    if not ahead or "pressure" not in fc.current:
        return None
    change = ahead[0] - fc.current["pressure"]
    if abs(change) < 1:
        return "steady"
    return "rising" if change > 0 else "falling"


class ImpressionCanvas(Canvas):
    def __init__(self, width, height):
        super().__init__(width, height, PALETTE, WHITE, DESIGN_WIDTH)
        self.footer_top = height - self.px(FOOTER_HEIGHT)


def pill(c, box, radius, fill):
    """A filled rounded rectangle. ImageDraw.rounded_rectangle needs Pillow 8.2; Bullseye ships 8.1."""
    x0, y0, x1, y1 = box
    c.draw.rectangle((x0 + radius, y0, x1 - radius, y1), fill=fill)
    c.draw.rectangle((x0, y0 + radius, x1, y1 - radius), fill=fill)
    for cx, cy in ((x0, y0), (x1 - 2 * radius, y0), (x0, y1 - 2 * radius), (x1 - 2 * radius, y1 - 2 * radius)):
        c.draw.ellipse((cx, cy, cx + 2 * radius, cy + 2 * radius), fill=fill)


def draw_icon(c, condition_id, night, box):
    """Draw a weather icon as large as fits box (left, top, right, bottom in design units), inked by
    condition. Icons differ in shape (a sun is wide, a storm cloud tall), so measure the drawn glyph."""
    kind = condition_kind(condition_id, night)
    glyph = GLYPHS[kind]
    left, top, right, bottom = (c.px(v) for v in box)
    size = (box[3] - box[1]) * 1.4
    while True:
        x0, y0, x1, y1 = c.font("icons", size).getbbox(glyph)
        if size <= 12 or (x1 - x0 <= right - left and y1 - y0 <= bottom - top):
            break
        size -= 2
    c.text_at((left - x0, top + (bottom - top - (y1 - y0)) / 2 - y0), glyph, "icons", size, fill=ICON_INKS.get(kind, BLACK))


def draw_now_panel(c, fc, units, evening):
    current = fc.current
    panel_right = c.px(292)

    draw_icon(c, current["weather"][0]["id"], fc.is_night, (10, 10, 116, 100))

    # Shrink the big temperature until it fits beside the icon (triple digits, negatives)
    temp_x, temp_text, size = 128, deg(current["temp"]), 76
    while size > 44 and c.text_width(temp_text, "bold", size) > panel_right - c.px(temp_x + 4):
        size -= 4
    c.text((temp_x, 2 + (76 - size) / 2), temp_text, "bold", size, fill=temp_ink(current["temp"], units))
    c.text((temp_x + 4, 90), f"Feels {deg(current['feels_like'])}", "regular", 20, fill=BLACK)

    description = current["weather"][0]["description"].capitalize()
    c.text((12, 116), c.fit(description, "bold", 22, panel_right - c.px(16)), "bold", 22, fill=BLACK)

    y = 144
    if evening:
        low = min((h["temp"] for h in fc.hours[:12]), default=fc.today["temp"]["min"])
        c.text((12, y), "Tonight", "regular", 20, fill=BLACK)
        x = 12 + c.text_width("Tonight ", "regular", 20) / c.scale
        c.text((x, y), f"↓{deg(low)}", "bold", 20, fill=temp_ink(low, units))
    else:
        high, low = fc.today["temp"]["max"], fc.today["temp"]["min"]
        c.text((12, y), f"↑{deg(high)}", "bold", 20, fill=temp_ink(high, units))
        x = 12 + c.text_width(f"↑{deg(high)}  ", "bold", 20) / c.scale
        c.text((x, y), f"↓{deg(low)}", "bold", 20, fill=temp_ink(low, units))


def detail_cells(fc, units, thresholds, evening):
    """(label, draw) pairs for the details grid; draw(c, x, y) renders the value line."""
    cells = []

    # Rain: today's chance before evening, the next 12 hours after
    if evening:
        hours = fc.hours[:12]
        pop = max((h.get("pop", 0) for h in hours), default=0)
        mm = sum(h.get("rain", {}).get("1h", 0) + h.get("snow", {}).get("1h", 0) for h in hours)
        label = "Rain tonight"
    else:
        pop = fc.today.get("pop", 0)
        mm = fc.today.get("rain", 0) + fc.today.get("snow", 0)
        label = "Rain today"

    def rain(c, x, y):
        pct = f"{round(pop * 100)}%"
        c.text((x, y), pct, "bold", 19, fill=BLUE if pop >= 0.2 else BLACK)
        if mm >= 0.25:
            c.text((x + c.text_width(pct, "bold", 19) / c.scale, y + 2), f" · {rain_amount(mm, units)}", "regular", 16, fill=BLACK)
    cells.append((label, rain))

    # Wind: direction and speed, orange once it crosses the callout thresholds
    wind, gusts = fc.current.get("wind_speed", 0), fc.current.get("wind_gust", 0)
    windy = wind >= thresholds["wind"] or gusts >= thresholds["gusts"]
    direction = compass(fc.current["wind_deg"]) + " " if "wind_deg" in fc.current else ""
    wind_label = f"Wind · gusts {round(gusts)}" if gusts > wind else "Wind"
    cells.append((wind_label, lambda c, x, y: c.text(
        (x, y), f"{direction}{round(wind)} {WIND_UNITS[units]}", "bold", 19, fill=ORANGE if windy else BLACK)))

    # UV: today's peak, or tomorrow's once evening starts
    uv_day = fc.next_days[0] if evening and fc.next_days else fc.today
    uvi = uv_day.get("uvi", 0)

    def uv(c, x, y):
        fill, ink, word = uv_style(uvi)
        number = str(round(uvi))
        width = c.text_width(number, "bold", 17) + c.px(14)
        pill(c, (c.px(x), c.px(y), c.px(x) + width, c.px(y + 23)), c.px(6), fill)
        c.text_at((c.px(x + 7), c.px(y + 2)), number, "bold", 17, fill=ink)
        c.text((x + width / c.scale + 6, y + 1), word, "bold", 17, fill=BLACK)
    cells.append(("UV tomorrow" if evening else "UV index today", uv))

    if "humidity" in fc.current:
        cells.append(("Humidity", lambda c, x, y: c.text((x, y), f"{fc.current['humidity']}%", "bold", 19, fill=BLACK)))

    if "pressure" in fc.current:
        trend = pressure_trend(fc)
        arrow = {"rising": " ↑", "falling": " ↓"}.get(trend, "")
        cells.append((f"Pressure · {trend}" if trend else "Pressure", lambda c, x, y: c.text(
            (x, y), pressure_text(fc.current["pressure"], units) + arrow, "bold", 19, fill=BLACK)))

    if "dew_point" in fc.current:
        dew = fc.current["dew_point"]
        cells.append((f"Dew point · {dew_point_word(dew, units)}", lambda c, x, y: c.text(
            (x, y), deg(dew), "bold", 19, fill=BLACK)))

    sunrise, sunset = fc.local(fc.today["sunrise"]), fc.local(fc.today["sunset"])

    def sun(c, x, y):
        text = f"{sunrise:%-I:%M} – {sunset:%-I:%M}"
        c.text((x, y), text, "bold", 19, fill=BLACK)
    cells.append(("Sunrise – sunset", sun))

    if "moon_phase" in fc.today:
        phase = fc.today["moon_phase"]

        def moon(c, x, y):
            # The phase icon sits on the label line, leaving the value line for the name
            c.text((x + 40, y - 18), moon_glyph(phase), "icons", 14, fill=BLACK)
            c.text((x, y + 2), c.fit(moon_name(phase), "bold", 15, c.px(142)), "bold", 15, fill=BLACK)
        cells.append(("Moon", moon))
    return cells[:8]


def draw_details(c, fc, units, thresholds, evening):
    left, top, column, row = 306, 6, 148, 41
    for i, (label, draw_value) in enumerate(detail_cells(fc, units, thresholds, evening)):
        x, y = left + column * (i % 2), top + row * (i // 2)
        c.text((x, y), c.fit(label, "regular", 13, c.px(column - 8)), "regular", 13, fill=BLACK)
        draw_value(c, x, y + 16)


def draw_hourly(c, fc, units):
    """Temperature line over rain-chance bars for the next 24 hours."""
    hours = fc.hours
    top, bottom = c.px(TOP_BOTTOM + 22), c.px(CHART_BOTTOM - 20)
    left, right = c.px(12), c.width - c.px(12)
    if len(hours) < 2:
        c.centered("No hourly forecast available", c.width / 2, (TOP_BOTTOM + CHART_BOTTOM) / 2 - 8, "regular", 16, fill=BLACK)
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
            c.draw.rectangle((int(x0 + c.px(2)), int(bottom - (bottom - top) * pop), int(x0 + step - c.px(2)), bottom - 1), fill=BLUE)
        y = bottom - c.px(8) - (hour["temp"] - t_min) / span * (bottom - top - c.px(22))
        points.append((x0 + step / 2, y))

        local = fc.local(hour["dt"])
        label_y = CHART_BOTTOM - 17
        if local.hour == 0 and i > 0:
            # A day name at midnight shows where tomorrow starts
            c.draw.line((x0, top, x0, bottom), fill=BLACK, width=1)
            c.centered(local.strftime("%a"), x0, label_y, "bold", 13, fill=BLACK)
        elif i % 3 == 0 and not (0 < 24 - local.hour < 2):
            label = "Now" if i == 0 else local.strftime("%-I%p").lower().rstrip("m")
            c.centered(label, x0 + step / 2, label_y, "regular", 13, fill=BLACK)

    # Each segment takes the ink of its warmer end, so a hot afternoon shows up as orange or red
    for (p0, p1), t0, t1 in zip(zip(points, points[1:]), temps, temps[1:]):
        c.draw.line((p0, p1), fill=temp_ink(max(t0, t1), units), width=c.px(4))
    c.draw.line((left, bottom, right, bottom), fill=BLACK, width=1)

    # Label the high and low just above the line; the low sits near the axis, so below would hit the labels
    labels = [t_max] if t_max == t_min else [t_max, t_min]
    for value in labels:
        x, y = points[temps.index(value)]
        text = deg(value)
        width = c.text_width(text, "bold", 15)
        c.text_at((min(max(x - width / 2, 0), c.width - width), y - c.px(22)), text, "bold", 15, fill=temp_ink(value, units))


def draw_week(c, fc, units):
    days = fc.next_days
    if not days:
        return
    column = c.width / len(days) if len(days) > 5 else c.width / 7
    for i, day in enumerate(days):
        cx = column * i + column / 2
        c.centered(fc.local(day["dt"]).strftime("%a"), cx, CHART_BOTTOM + 4, "bold", 16, fill=BLACK)
        kind = condition_kind(day["weather"][0]["id"])
        glyph = weather_glyph(day["weather"][0]["id"])
        c.centered(glyph, cx, CHART_BOTTOM + 18, "icons", 32, fill=ICON_INKS.get(kind, BLACK))
        high, low = day["temp"]["max"], day["temp"]["min"]
        c.centered(deg(high), cx, CHART_BOTTOM + 62, "bold", 20, fill=temp_ink(high, units))
        c.centered(deg(low), cx, CHART_BOTTOM + 85, "regular", 17, fill=temp_ink(low, units))
        if day.get("pop", 0) >= 0.1:
            pct = f"{round(day['pop'] * 100)}%"
            start = cx - (c.px(14) + c.text_width(pct, "bold", 14)) / 2
            c.text_at((start, c.px(CHART_BOTTOM + 102)), GLYPHS["raindrop"], "icons", 14, fill=BLUE)
            c.text_at((start + c.px(14), c.px(CHART_BOTTOM + 103)), pct, "bold", 14, fill=BLUE)


def draw_banner(c, text, suffix="", fill=BLACK):
    """White-on-color footer. When space runs out, text is shortened and suffix is always kept whole."""
    c.draw.rectangle((0, c.footer_top, c.width, c.height), fill=fill)
    room = c.width - c.px(16) - c.text_width(suffix, "bold", 16)
    c.centered(c.fit(text, "bold", 16, room) + suffix, c.width / 2, c.footer_top / c.scale + 4, "bold", 16, fill=WHITE)


def draw_footer(c, fc, units, thresholds, evening, updated_at, offline_since):
    if offline_since:
        since = fc.local(offline_since.timestamp())
        when = clock(since) if since.date() == fc.now.date() else since.strftime("%a ") + clock(since)
        draw_banner(c, f"OFFLINE · forecast from {when}")
        return

    alerts = fc.active_alerts()
    if alerts:
        first = alerts[0]
        end = fc.local(first["end"])
        until = end.strftime("%-I %p") if end.date() == fc.now.date() else end.strftime("%a %-I %p")
        suffix = f" until {until}"
        if len(alerts) > 1:
            suffix += f" (+{len(alerts) - 1} more)"
        draw_banner(c, f"⚠ {first['event']}", suffix, fill=RED)
        return

    c.draw.line((0, c.footer_top, c.width, c.footer_top), fill=BLACK, width=c.px(2))
    y = (c.footer_top + c.px(6)) / c.scale
    stamp = f"Updated {clock(fc.local(updated_at.timestamp()))}"
    stamp_width = c.text_width(stamp, "regular", 14)
    c.text_at((c.width - c.px(8) - stamp_width, c.px(y)), stamp, "regular", 14, fill=BLACK)

    room = c.width - c.px(24) - stamp_width
    swing = fc.next_days[0]["temp"]["max"] - fc.today["temp"]["max"] if fc.next_days else 0
    if abs(swing) >= thresholds["temp_swing"]:
        word = "warmer" if swing > 0 else "colder"
        c.text((8, y - 1), f"{'↑' if swing > 0 else '↓'}{deg(abs(swing))} {word} tomorrow", "bold", 15,
               fill=ORANGE if swing > 0 else BLUE)
        return
    day = fc.next_days[0] if evening and fc.next_days else fc.today
    if day.get("summary"):
        prefix = "Tomorrow: " if day is not fc.today else ""
        c.text((8, y), c.fit(prefix + day["summary"].rstrip(".") + ".", "regular", 14, room), "regular", 14, fill=BLACK)


def render(data, units, thresholds, now, size=(600, 448), accent=None, evening_starts=18, offline_since=None):
    """Draw the full screen as a palette image in the Impression's ink order.

    now and offline_since are timezone-aware datetimes. offline_since marks the data as a cached
    forecast and replaces the footer with an offline banner. accent is unused: every ink is available.
    """
    fc = Forecast(data, now, hours=24, days=7)
    evening = fc.now.hour >= evening_starts

    c = ImpressionCanvas(*size)
    draw_now_panel(c, fc, units, evening)
    draw_details(c, fc, units, thresholds, evening)
    c.draw.line((c.px(296), c.px(8), c.px(296), c.px(TOP_BOTTOM - 8)), fill=BLACK, width=c.px(2))
    c.draw.line((0, c.px(TOP_BOTTOM), c.width, c.px(TOP_BOTTOM)), fill=BLACK, width=c.px(2))
    draw_hourly(c, fc, units)
    c.draw.line((0, c.px(CHART_BOTTOM), c.width, c.px(CHART_BOTTOM)), fill=BLACK, width=c.px(2))
    draw_week(c, fc, units)
    draw_footer(c, fc, units, thresholds, evening, updated_at=now, offline_since=offline_since)
    return c.image
