"""The Inky Impression 5.7" layout (600x448, 7 inks), from a One Call API 3.0 response.

    +--------------------------+-------------------------------+
    | icon  48°                | Rain today      Wind          |  now, plus a details grid
    |       Feels 45°          | [70%] 0.17 in   W 9 mph       |
    | Few clouds               | UV index        Humidity      |
    | ↑61°  ↓45°               | [4] Moderate    71%           |
    |                          | Pressure        Dew point     |
    |                          | Sun             Moon          |
    +--------------------------+-------------------------------+
    |  next 24 hours: temperature line over rain-chance bars   |
    +----------------------------------------------------------+
    |  Thu   Fri   Sat   Sun   Mon   Tue   Wed                 |  next seven days, with
    |  icon  icon  ...                                         |  high-low bars on a shared
    |  ▮54°  ▮57°  ...                                         |  temperature scale
    |  ▮41°  ▮44°  ...                                         |
    +----------------------------------------------------------+
    | the day's summary, over up to two lines  Updated 7:30 AM |  or an alert/offline banner
    +----------------------------------------------------------+

On this panel blue and green print dark, close to black, and yellow, orange, and red are the only
inks that read as clearly colored. So color goes into solid shapes (badges, bars, filled icons),
never thin colored text, and every shape carries a meaning:

    temperature   blue ≤40°F, green 41-59, yellow 60-74, orange 75-84, red ≥85 (metric 4/15/23/29)
    rain          blue bars, badges, and rain clouds
    sun           yellow discs with orange rays
    alerts        a red banner
    UV index      the standard green-yellow-orange-red badge

Every color is one of the panel's pure inks, so nothing is dithered.
"""
from PIL import Image, ImageDraw

from .common import (GLYPHS, WIND_UNITS, Canvas, Forecast, clock, compass, condition_kind, deg,
                     font, moon_glyph, moon_name)

DESIGN_WIDTH = 600

# The panel's ink order, as used by Pimoroni's inky library for the Impression
BLACK, WHITE, GREEN, BLUE, RED, YELLOW, ORANGE = range(7)
# Colors as measured on a real panel (inky's SATURATED_PALETTE), so previews show what the wall will:
# blue reads close to black, and orange and yellow are soft. The panel itself only sees the indices.
PALETTE = [(57, 48, 57), (255, 255, 255), (58, 91, 70), (61, 59, 94), (156, 72, 75), (208, 190, 71), (177, 106, 73)]

# Temperature bands: (highest value in the band, ink), a conventional weather-map scale
TEMP_BANDS = {
    "imperial": ((40, BLUE), (59, GREEN), (74, YELLOW), (84, ORANGE), (None, RED)),
    "metric": ((4, BLUE), (15, GREEN), (23, YELLOW), (29, ORANGE), (None, RED)),
}
# Dew point comfort, the usual US National Weather Service wording
DEW_POINT_BANDS = {"imperial": ((50, "dry"), (60, "comfortable"), (65, "sticky"), (70, "humid")),
                   "metric": ((10, "dry"), (16, "comfortable"), (18, "sticky"), (21, "humid"))}

TOP_BOTTOM = 172      # end of the now panel and details grid
CHART_BOTTOM = 284    # end of the 24-hour chart, including its hour labels
FOOTER_HEIGHT = 42    # two lines, so the day's summary and alert names fit


def temp_ink(value, units):
    for top, ink in TEMP_BANDS[units]:
        if top is None or round(value) <= top:
            return ink


def band_edges(units):
    """Temperatures where one band ends and the next begins, e.g. 40.5 between blue and green."""
    return [top + 0.5 for top, _ in TEMP_BANDS[units] if top is not None]


def uv_style(uvi):
    """(badge fill, text ink, word) on the WHO UV index scale."""
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


def wrap(c, text, kind, size, widths):
    """Break text into lines no wider than each of widths (screen pixels). The last line gets an
    ellipsis if the text still doesn't fit."""
    words, lines = text.split(), []
    for i, width in enumerate(widths):
        line = ""
        while words and c.text_width((line + " " + words[0]).strip(), kind, size) <= width:
            line = (line + " " + words.pop(0)).strip()
        if not line and words:
            line = words.pop(0)  # a single word wider than the line; fit() trims it below
        if i == len(widths) - 1 and words:
            line = c.fit(line + " " + " ".join(words), kind, size, width, force_ellipsis=False)
        lines.append(line if c.text_width(line, kind, size) <= width else c.fit(line, kind, size, width))
    return [line for line in lines if line]


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


def badge(c, x, y, text, fill, ink, size=17):
    """Text on a solid rounded badge at (x, y) design units; returns its width in design units."""
    width = c.text_width(text, "bold", size) + c.px(14)
    pill(c, (c.px(x), c.px(y), c.px(x) + width, c.px(y + size + 6)), c.px(6), fill)
    c.text_at((c.px(x + 7), c.px(y + 2)), text, "bold", size, fill=ink)
    return width / c.scale


# How each icon is colored. The glyph's largest stroke is its main shape (the cloud, or the sun's
# disc); other strokes are rays, drops, flakes, or a bolt. Holes are the areas the strokes enclose.
#   main / other: stroke inks.  hole / other_hole: fills for the largest and other enclosed areas.
#   bolt: ink for the largest non-main stroke (the lightning).  close: the cloud is open at the
#   bottom (precipitation glyphs) and must be closed before it can be filled.
ICON_STYLES = {
    "day_clear": {"main": ORANGE, "other": ORANGE, "hole": YELLOW},
    "day_partly": {"main": BLACK, "other": ORANGE, "hole": WHITE, "other_hole": YELLOW},
    "rain": {"main": BLACK, "other": BLUE, "hole": BLUE, "close": True},
    "showers": {"main": BLACK, "other": BLUE, "hole": BLUE, "close": True},
    "storm": {"main": BLACK, "other": BLUE, "hole": BLUE, "bolt": YELLOW, "close": True},
    "snow": {"main": BLACK, "other": BLUE, "close": True},
}


def _label(image, value, start):
    """Give each 4-connected area of pixels equal to value its own label from start up; return them."""
    labels, px = [], image.load()
    width, height = image.size
    for y in range(height):
        for x in range(width):
            if px[x, y] == value:
                ImageDraw.floodfill(image, (x, y), start + len(labels))
                labels.append(start + len(labels))
    return labels


def icon_layers(glyph, size, style):
    """Split a glyph into (ink, mask) layers per ICON_STYLES. Returns (layers, bbox offset)."""
    f = font("icons", size)
    x0, y0, x1, y1 = f.getbbox(glyph)
    pad = 2
    w, h = x1 - x0 + 2 * pad, y1 - y0 + 2 * pad
    ink = Image.new("L", (w, h), 0)
    ImageDraw.Draw(ink).text((pad - x0, pad - y0), glyph, font=f, fill=255)
    ink = ink.point(lambda v: 255 if v >= 128 else 0)

    # Label strokes: 0 = open, 1 = ink, then one label per stroke from 10 up
    strokes = ink.point(lambda v: 1 if v else 0)
    stroke_ids = _label(strokes, 1, 10)
    counts = strokes.histogram()
    stroke_ids.sort(key=lambda k: -counts[k])
    main = stroke_ids[0] if stroke_ids else None

    # Find enclosed areas, first closing an open-bottomed cloud with a line between its two ends
    closed = ink.copy()
    if style.get("close") and main is not None:
        sp = strokes.load()
        cloud = [(x, y) for y in range(h) for x in range(w) if sp[x, y] == main]
        # The opening's ends are the lowest points at the cloud's far left and right. Looking only at
        # the outer quarters skips any rain streak that touches the cloud in the middle.
        lo_x, hi_x = min(x for x, _ in cloud), max(x for x, _ in cloud)
        quarter = (hi_x - lo_x) / 4
        left = max((p for p in cloud if p[0] <= lo_x + quarter), key=lambda p: p[1], default=None)
        right = max((p for p in cloud if p[0] >= hi_x - quarter), key=lambda p: p[1], default=None)
        if left and right:
            ImageDraw.Draw(closed).line((left, right), fill=255, width=max(2, size // 14))
    holes = closed.point(lambda v: 1 if v else 0)
    ImageDraw.floodfill(holes, (0, 0), 2)
    hole_ids = _label(holes, 0, 10)
    hole_counts = holes.histogram()
    hole_ids.sort(key=lambda k: -hole_counts[k])

    def mask_of(image, ids):
        wanted = set(ids)
        return image.point(lambda v: 255 if v in wanted else 0)

    layers = []
    if hole_ids and style.get("hole") is not None:
        # The closing line counts as part of the fill, so a rain cloud reads as one solid shape
        main_hole = mask_of(holes, hole_ids[:1])
        if style.get("close"):
            seam = Image.composite(closed, Image.new("L", (w, h), 0), ink.point(lambda v: 0 if v else 255))
            main_hole = Image.composite(Image.new("L", (w, h), 255), main_hole, seam)
        layers.append((style["hole"], main_hole))
    if len(hole_ids) > 1 and style.get("other_hole") is not None:
        layers.append((style["other_hole"], mask_of(holes, hole_ids[1:])))
    if main is not None:
        layers.append((style.get("main", BLACK), mask_of(strokes, [main])))
    others = stroke_ids[1:]
    if others and style.get("bolt") is not None:
        layers.append((style["bolt"], mask_of(strokes, others[:1])))
        others = others[1:]
    if others:
        layers.append((style.get("other", BLACK), mask_of(strokes, others)))
    return layers, (x0 - pad, y0 - pad)


def draw_icon(c, condition_id, night, box):
    """Draw a weather icon, filled and colored by condition, as large as fits box (left, top, right,
    bottom in design units), centered in the box."""
    kind = condition_kind(condition_id, night)
    glyph = GLYPHS[kind]
    left, top, right, bottom = (c.px(v) for v in box)
    size = int((bottom - top) * 1.4)
    while True:
        x0, y0, x1, y1 = font("icons", size).getbbox(glyph)
        if size <= 12 or (x1 - x0 <= right - left and y1 - y0 <= bottom - top):
            break
        size -= 2
    origin = (round(left + (right - left - (x1 - x0)) / 2), round(top + (bottom - top - (y1 - y0)) / 2))
    style = ICON_STYLES.get(kind)
    if style is None:
        c.text_at((origin[0] - x0, origin[1] - y0), glyph, "icons", size, fill=BLACK)
        return
    layers, (ox, oy) = icon_layers(glyph, size, style)
    at = (origin[0] - (x0 - ox) + 0, origin[1] - (y0 - oy))
    for ink, mask in layers:
        c.image.paste(ink, (at[0], at[1], at[0] + mask.width, at[1] + mask.height), mask)


def draw_now_panel(c, fc, units, evening):
    current = fc.current
    panel_right = c.px(292)

    draw_icon(c, current["weather"][0]["id"], fc.is_night, (6, 10, 118, 100))

    # Shrink the big temperature until it fits beside the icon (triple digits, negatives)
    temp_x, temp_text, size = 128, deg(current["temp"]), 76
    while size > 44 and c.text_width(temp_text, "bold", size) > panel_right - c.px(temp_x + 4):
        size -= 4
    c.text((temp_x, 2 + (76 - size) / 2), temp_text, "bold", size, fill=BLACK)
    c.text((temp_x + 4, 90), f"Feels {deg(current['feels_like'])}", "regular", 20, fill=BLACK)

    description = current["weather"][0]["description"].capitalize()
    c.text((12, 116), c.fit(description, "bold", 22, panel_right - c.px(16)), "bold", 22, fill=BLACK)

    y = 144
    if evening:
        low = min((h["temp"] for h in fc.hours[:12]), default=fc.today["temp"]["min"])
        c.text((12, y), f"Tonight ↓{deg(low)}", "bold", 20, fill=BLACK)
    else:
        c.text((12, y), f"↑{deg(fc.today['temp']['max'])}  ↓{deg(fc.today['temp']['min'])}", "bold", 20, fill=BLACK)


def detail_cells(fc, units, thresholds, evening):
    """(label, draw) pairs for the details grid; draw(c, x, y) renders the value line."""
    cells = []

    # Rain: today's chance before evening, the next 12 hours after; a blue badge from 20%
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
        if pop >= 0.2:
            width = badge(c, x, y, pct, BLUE, WHITE)
        else:
            c.text((x, y), pct, "bold", 19, fill=BLACK)
            width = c.text_width(pct, "bold", 19) / c.scale
        if mm >= 0.25:
            c.text((x + width + 6, y + 3), rain_amount(mm, units), "regular", 16, fill=BLACK)
    cells.append((label, rain))

    # Wind: direction and speed, on an orange badge once it crosses the callout thresholds
    wind, gusts = fc.current.get("wind_speed", 0), fc.current.get("wind_gust", 0)
    windy = wind >= thresholds["wind"] or gusts >= thresholds["gusts"]
    direction = compass(fc.current["wind_deg"]) + " " if "wind_deg" in fc.current else ""
    wind_label = f"Wind · gusts {round(gusts)}" if gusts > wind else "Wind"
    wind_text = f"{direction}{round(wind)} {WIND_UNITS[units]}"

    def wind_value(c, x, y):
        if windy:
            badge(c, x, y, wind_text, ORANGE, BLACK)
        else:
            c.text((x, y), wind_text, "bold", 19, fill=BLACK)
    cells.append((wind_label, wind_value))

    # UV: today's peak, or tomorrow's once evening starts
    uv_day = fc.next_days[0] if evening and fc.next_days else fc.today
    uvi = uv_day.get("uvi", 0)

    def uv(c, x, y):
        fill, ink, word = uv_style(uvi)
        width = badge(c, x, y, str(round(uvi)), fill, ink)
        c.text((x + width + 6, y + 1), word, "bold", 17, fill=BLACK)
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
        c.text((x, y), f"{sunrise:%-I:%M} – {sunset:%-I:%M}", "bold", 19, fill=BLACK)
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
    top, bottom = c.px(TOP_BOTTOM + 24), c.px(CHART_BOTTOM - 20)
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
        y = bottom - c.px(10) - (hour["temp"] - t_min) / span * (bottom - top - c.px(26))
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

    # A thick line colored by temperature band, outlined in black so yellow stays visible, with a
    # white halo so it never merges with the (dark) rain bars underneath
    segments = list(zip(points, points[1:]))
    for width, ink in ((12, WHITE), (8, BLACK)):
        for p0, p1 in segments:
            c.draw.line((p0, p1), fill=ink, width=c.px(width))
        for x, y in points:
            r = c.px(width) / 2
            c.draw.ellipse((x - r, y - r, x + r, y + r), fill=ink)
    for (p0, p1), t0, t1 in zip(segments, temps, temps[1:]):
        c.draw.line((p0, p1), fill=temp_ink((t0 + t1) / 2, units), width=c.px(4))
    c.draw.line((left, bottom, right, bottom), fill=BLACK, width=1)

    # Label the high and low just above the line; the low sits near the axis, so below would hit the labels
    labels = [t_max] if t_max == t_min else [t_max, t_min]
    for value in labels:
        x, y = points[temps.index(value)]
        text = deg(value)
        width = c.text_width(text, "bold", 15)
        c.text_at((min(max(x - width / 2, 0), c.width - width), y - c.px(24)), text, "bold", 15, fill=BLACK)


def draw_temp_bar(c, x, y_of, low, high, units, width):
    """A vertical bar from low to high, split into its temperature-band colors and outlined in black.
    x is the left edge in screen pixels; y_of maps a temperature to a screen y."""
    edges = [e for e in band_edges(units) if low < e < high]
    stops = [low] + edges + [high]
    for t0, t1 in zip(stops, stops[1:]):
        c.draw.rectangle((x, round(y_of(t1)), x + width, round(y_of(t0))), fill=temp_ink((t0 + t1) / 2, units))
    c.draw.rectangle((x, round(y_of(high)), x + width, round(y_of(low))), outline=BLACK, width=1)


def draw_week(c, fc, units, show_rain=True):
    """Seven columns: day name and rain chance, icon, and a high-low bar on the week's shared scale."""
    days = fc.next_days
    if not days:
        return
    column = c.width / max(len(days), 7)
    lows, highs = [d["temp"]["min"] for d in days], [d["temp"]["max"] for d in days]
    w_min, w_max = min(lows), max(highs)
    span = max(w_max - w_min, 10)
    bar_top, bar_bottom = c.px(CHART_BOTTOM + 58), c.px(CHART_BOTTOM + 111)

    def y_of(t):
        return bar_bottom - (t - w_min) / span * (bar_bottom - bar_top)

    label_size = 14
    label_height = c.px(label_size + 1)
    for i, day in enumerate(days):
        cx = column * i + column / 2
        c.centered(fc.local(day["dt"]).strftime("%a"), cx, CHART_BOTTOM + 3, "bold", 15, fill=BLACK)

        # Icon, with the rain chance beside it when it's 10% or more
        pct = f"{round(day.get('pop', 0) * 100)}%" if show_rain and day.get("pop", 0) >= 0.1 else ""
        icon_box = (cx - c.px(37 if pct else 30), cx + c.px(3 if pct else 30))
        draw_icon(c, day["weather"][0]["id"], False, (icon_box[0] / c.scale, CHART_BOTTOM + 21,
                                                      icon_box[1] / c.scale, CHART_BOTTOM + 47))
        if pct:
            c.text_at((cx + c.px(5), c.px(CHART_BOTTOM + 27)), GLYPHS["raindrop"], "icons", 12, fill=BLUE)
            c.text_at((cx + c.px(16), c.px(CHART_BOTTOM + 28)), pct, "bold", 12, fill=BLACK)

        # High-low bar on the week's shared scale, with the numbers beside its ends
        high, low = day["temp"]["max"], day["temp"]["min"]
        bar_width = c.px(14)
        bar_x = round(cx - c.px(22))
        top_y, bottom_y = y_of(high), y_of(low)
        if bottom_y - top_y < c.px(4):  # keep a near-flat day visible
            top_y -= c.px(2)
            bottom_y += c.px(2)
        draw_temp_bar(c, bar_x, lambda t: top_y + (bottom_y - top_y) * (high - t) / max(high - low, 0.01),
                      low, high, units, bar_width)
        hi_y = top_y - label_height / 2
        lo_y = max(bottom_y - label_height / 2, hi_y + label_height)
        label_x = bar_x + bar_width + c.px(5)
        c.text_at((label_x, hi_y), deg(high), "bold", label_size, fill=BLACK)
        c.text_at((label_x, lo_y), deg(low), "regular", label_size, fill=BLACK)



def draw_banner(c, title, detail, fill):
    """Two-line white-on-color footer: a bold title, and a smaller detail line under it."""
    c.draw.rectangle((0, c.footer_top, c.width, c.height), fill=fill)
    top = c.footer_top / c.scale
    c.centered(c.fit(title, "bold", 17, c.width - c.px(16)), c.width / 2, top + 3, "bold", 17, fill=WHITE)
    c.centered(c.fit(detail, "regular", 14, c.width - c.px(16)), c.width / 2, top + 23, "regular", 14, fill=WHITE)


def draw_footer(c, fc, units, thresholds, evening, updated_at, offline_since):
    if offline_since:
        since = fc.local(offline_since.timestamp())
        when = clock(since) if since.date() == fc.now.date() else since.strftime("%a ") + clock(since)
        draw_banner(c, "OFFLINE", f"Showing the forecast from {when}", BLACK)
        return

    alerts = fc.active_alerts()
    if alerts:
        first = alerts[0]
        end = fc.local(first["end"])
        until = end.strftime("%-I %p") if end.date() == fc.now.date() else end.strftime("%a %-I %p")
        detail = f"Until {until}"
        if len(alerts) > 1:
            others = ", ".join(a["event"] for a in alerts[1:])
            detail += f" · also {others}"
        draw_banner(c, f"⚠ {first['event']}", detail, RED)
        return

    c.draw.line((0, c.footer_top, c.width, c.footer_top), fill=BLACK, width=c.px(2))
    top = c.footer_top / c.scale
    lines_y = (top + 5, top + 23)
    stamp = f"Updated {clock(fc.local(updated_at.timestamp()))}"
    stamp_width = c.text_width(stamp, "regular", 14)
    c.text_at((c.width - c.px(8) - stamp_width, c.px(lines_y[0])), stamp, "regular", 14, fill=BLACK)
    first_width, full_width = c.width - c.px(28) - stamp_width, c.width - c.px(16)

    day = fc.next_days[0] if evening and fc.next_days else fc.today
    summary = ""
    if day.get("summary"):
        summary = ("Tomorrow: " if day is not fc.today else "") + day["summary"].rstrip(".") + "."

    swing = fc.next_days[0]["temp"]["max"] - fc.today["temp"]["max"] if fc.next_days else 0
    if abs(swing) >= thresholds["temp_swing"]:
        # The swing takes the first line; the summary, if any, gets the second
        word = "warmer" if swing > 0 else "colder"
        c.text((8, lines_y[0] - 1), f"{'↑' if swing > 0 else '↓'}{deg(abs(swing))} {word} tomorrow", "bold", 15,
               fill=RED if swing > 0 else BLUE)
        if summary:
            c.text((8, lines_y[1]), c.fit(summary, "regular", 14, full_width), "regular", 14, fill=BLACK)
        return
    for y, line in zip(lines_y, wrap(c, summary, "regular", 14, [first_width, full_width])):
        c.text((8, y), line, "regular", 14, fill=BLACK)


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
