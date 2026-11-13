"""Behavior tests with the network and display stubbed out. Run: python3 -m unittest discover tests"""
import copy
import json
import logging
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import layouts  # noqa: E402
import weather_station as ws  # noqa: E402
from displays import SCREENS  # noqa: E402
from layouts import common, impression  # noqa: E402
from layouts import compact as layout  # noqa: E402

SAMPLE = json.loads((ROOT / "sample_data.json").read_text())
logging.disable(logging.CRITICAL)


def write_config(path, quiet="", **display):
    text = (ROOT / "config.example.ini").read_text()
    text = text.replace("YOUR_OPENWEATHER_API_KEY", "abc123").replace("YOUR_LATITUDE", "51.51").replace("YOUR_LONGITUDE", "-0.13")
    lines = []
    for line in text.splitlines():
        key = line.split(" =")[0]
        if key == "quiet_hours":
            line = f"quiet_hours = {quiet}"
        elif key in display:
            line = f"{key} = {display[key]}"
        lines.append(line)
    path.write_text("\n".join(lines) + "\n")


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "config.ini"

    def test_defaults_follow_units(self):
        write_config(self.path)
        cfg = ws.load_config(self.path)
        self.assertEqual(cfg["thresholds"], ws.DEFAULT_THRESHOLDS["imperial"])
        self.assertIsNone(cfg["quiet_hours"])

    def test_overrides_and_wraparound(self):
        write_config(self.path, quiet="23-6", wind="20")
        cfg = ws.load_config(self.path)
        self.assertEqual(cfg["quiet_hours"], (23, 6))
        self.assertEqual(cfg["thresholds"]["wind"], 20)

    def test_rejects_bad_values(self):
        for kwargs in ({"quiet": "5"}, {"quiet": "0-25"}, {"wind": "lots"}, {"screen": "kindle"}, {"rotate": "90"}):
            write_config(self.path, **kwargs)
            with self.assertRaises(ws.StationError):
                ws.load_config(self.path)

    def test_config_without_display_section(self):
        self.path.write_text("[openweather]\napi_key = abc123\nlatitude = 1\nlongitude = 2\n")
        cfg = ws.load_config(self.path)
        self.assertIsNone(cfg["quiet_hours"])
        self.assertEqual(cfg["evening_starts"], 18)
        self.assertEqual(cfg["screen"], "waveshare_3in52")
        self.assertEqual(cfg["rotate"], 0)

    def test_in_hours(self):
        self.assertTrue(ws.in_hours(4, (0, 5)))
        self.assertFalse(ws.in_hours(5, (0, 5)))
        self.assertTrue(ws.in_hours(23, (23, 6)) and ws.in_hours(2, (23, 6)))
        self.assertFalse(ws.in_hours(6, (23, 6)) or ws.in_hours(22, (23, 6)))


class MainTests(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.config = tmp / "config.ini"
        write_config(self.config)
        self.shown = []
        self.network_up = True
        patches = [
            mock.patch.object(ws, "CONFIG_PATH", self.config),
            mock.patch.object(ws, "CACHE_PATH", tmp / "last_forecast.json"),
            mock.patch.object(ws, "SHOWN_PATH", tmp / ".last_display"),
            mock.patch.object(ws, "LOCK_PATH", tmp / ".update.lock"),
            mock.patch.object(ws, "fetch_weather", self.fake_fetch),
            mock.patch.object(ws, "show", self.fake_show),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def fake_show(self, screen, image, deep_clean=False):
        self.shown.append(deep_clean)
        self.last = (screen, image)

    def fake_fetch(self, cfg):
        if not self.network_up:
            raise ws.FetchError("Could not reach OpenWeather (ConnectionError).")
        data = copy.deepcopy(SAMPLE)
        data["current"]["dt"] = int(datetime.now(timezone.utc).timestamp())
        return data

    def test_update_draws_and_caches(self):
        self.assertEqual(ws.main([]), 0)
        self.assertEqual(self.shown, [False])
        self.assertTrue(ws.CACHE_PATH.exists())

    def test_offline_uses_cache_and_skips_identical_redraws(self):
        ws.main([])
        self.network_up = False
        self.shown.clear()
        self.assertEqual(ws.main([]), 0)
        self.assertEqual(self.shown, [False])  # redrawn once with the offline banner
        self.assertEqual(ws.main([]), 0)
        self.assertEqual(self.shown, [False])  # unchanged, so no second flash
        self.assertEqual(ws.main(["--force"]), 0)
        self.assertEqual(self.shown, [False, False])

    def test_offline_without_cache_leaves_panel_alone(self):
        self.network_up = False
        self.assertEqual(ws.main([]), 1)
        self.assertEqual(self.shown, [])

    def test_inky_screens_render_at_their_size(self):
        for screen, size in (("inky_what", (400, 300)), ("inky_impression_5in7", (600, 448))):
            write_config(self.config, screen=screen, rotate="180")
            self.assertEqual(ws.main(["--force"]), 0)
            self.assertEqual(self.last[0], screen)
            self.assertEqual(self.last[1].size, size)

    def test_quiet_hours(self):
        hour = datetime.now().hour
        write_config(self.config, quiet=f"{hour}-{(hour + 1) % 24}")
        self.assertEqual(ws.main([]), 0)
        self.assertEqual(self.shown, [])
        self.assertEqual(ws.main(["--deep-clean"]), 0)  # the scheduled deep clean still runs
        self.assertEqual(self.shown, [True])


class LayoutTests(unittest.TestCase):
    """The compact layout used by the Waveshare 3.52" and Inky wHAT."""

    def test_screen_sizes_and_accent(self):
        stormy = copy.deepcopy(SAMPLE)
        stormy["alerts"] = [{"event": "Flood Warning", "start": 0, "end": SAMPLE["current"]["dt"] + 86400}]
        for screen, profile in SCREENS.items():
            if profile.layout != "compact":
                continue
            image = layouts.render(screen, stormy, "imperial", self.T, self.NOW)
            self.assertEqual(image.size, profile.size)
            used = {index for _, index in image.getcolors()}
            # Red screens use the accent ink for rain and alerts; black-and-white screens never do
            self.assertEqual(layout.ACCENT in used, profile.accent is not None, screen)

    T = ws.DEFAULT_THRESHOLDS["imperial"]
    NOW = datetime.fromtimestamp(SAMPLE["current"]["dt"], timezone.utc)

    def render(self, data, hours=0, **kwargs):
        image = layout.render(data, "imperial", self.T, self.NOW + timedelta(hours=hours), **kwargs)
        self.assertEqual(image.size, (360, 240))
        return image

    def test_states_render(self):
        stormy = copy.deepcopy(SAMPLE)
        stormy["alerts"] = [{"event": "Severe Thunderstorm Warning", "start": 0, "end": SAMPLE["current"]["dt"] + 86400}]
        self.render(SAMPLE)
        self.render(SAMPLE, hours=12)  # evening
        self.render(stormy)
        self.render(SAMPLE, hours=3, offline_since=self.NOW)
        self.render(SAMPLE, hours=72)  # stale cache: past the hourly and daily data

    def test_forecast_selects_by_time(self):
        fc = layout.Forecast(SAMPLE, self.NOW + timedelta(hours=3))
        self.assertGreater(fc.hours[0]["dt"], SAMPLE["current"]["dt"])
        self.assertEqual([fc.local(d["dt"]).strftime("%a") for d in fc.next_days], ["Thu", "Fri", "Sat"])

    def test_callouts_respect_thresholds(self):
        fc = layout.Forecast(SAMPLE, self.NOW)
        notes = [text for _, text in layout.notable_conditions(fc, "imperial", self.T, evening=False)]
        self.assertEqual(notes, ["70%"])  # 9 mph wind and UV 4 stay hidden
        windy = copy.deepcopy(SAMPLE)
        windy["current"]["wind_gust"] = 40
        fc = layout.Forecast(windy, self.NOW)
        notes = [text for _, text in layout.notable_conditions(fc, "imperial", self.T, evening=False)]
        self.assertIn("gusts 40", notes)


class ImpressionTests(unittest.TestCase):
    """The 7-color Inky Impression 5.7" layout."""

    T = ws.DEFAULT_THRESHOLDS["imperial"]
    NOW = datetime.fromtimestamp(SAMPLE["current"]["dt"], timezone.utc)

    def render(self, data, hours=0, **kwargs):
        image = layouts.render("inky_impression_5in7", data, "imperial", self.T, self.NOW + timedelta(hours=hours), **kwargs)
        self.assertEqual(image.size, (600, 448))
        return {index for _, index in image.getcolors()}

    def test_states_render_with_only_panel_inks(self):
        stormy = copy.deepcopy(SAMPLE)
        stormy["alerts"] = [{"event": "Severe Thunderstorm Warning", "start": 0, "end": SAMPLE["current"]["dt"] + 86400}]
        for inks in (self.render(SAMPLE), self.render(SAMPLE, hours=12), self.render(stormy),
                     self.render(SAMPLE, hours=3, offline_since=self.NOW), self.render(SAMPLE, hours=72)):
            self.assertLessEqual(inks, set(range(7)))  # pure inks only; nothing for the panel to dither

    def test_colors_carry_meaning(self):
        inks = self.render(SAMPLE)
        self.assertIn(impression.BLUE, inks)        # rain bars and badge
        self.assertIn(impression.YELLOW, inks)      # sun discs and mild temperatures
        self.assertIn(impression.ORANGE, inks)      # sun rays and the warm Monday
        self.assertNotIn(impression.RED, inks)      # nothing hot, no alerts
        stormy = copy.deepcopy(SAMPLE)
        stormy["alerts"] = [{"event": "Flood Warning", "start": 0, "end": SAMPLE["current"]["dt"] + 86400}]
        self.assertIn(impression.RED, self.render(stormy))

    def test_missing_optional_fields(self):
        # Fields the compact layout never needed may be absent; the details grid just shows less
        sparse = copy.deepcopy(SAMPLE)
        for key in ("humidity", "pressure", "dew_point", "wind_deg"):
            sparse["current"].pop(key)
        for day in sparse["daily"]:
            for key in ("moon_phase", "summary", "rain"):
                day.pop(key, None)
        self.render(sparse)
        self.render(sparse, hours=12)
        cells = impression.detail_cells(impression.Forecast(sparse, self.NOW, hours=24, days=7), "imperial", self.T, False)
        self.assertEqual([label for label, _ in cells], ["Rain today", "Wind · gusts 14", "UV index today", "Sunrise – sunset"])

    def test_icons_are_filled(self):
        # Sun discs fill yellow; rain and storm clouds, open at the bottom in the font, fill blue
        for kind, fill in (("day_clear", impression.YELLOW), ("rain", impression.BLUE), ("storm", impression.BLUE),
                           ("showers", impression.BLUE)):
            layers, _ = impression.icon_layers(common.GLYPHS[kind], 60, impression.ICON_STYLES[kind])
            fills = {}
            for ink, mask in layers:
                fills[ink] = fills.get(ink, 0) + mask.histogram()[255]
            self.assertGreater(fills.get(fill, 0), 200, kind)
        layers, _ = impression.icon_layers(common.GLYPHS["storm"], 60, impression.ICON_STYLES["storm"])
        self.assertIn(impression.YELLOW, [ink for ink, _ in layers])  # the bolt

    def test_long_summary_wraps_instead_of_trimming(self):
        c = impression.ImpressionCanvas(600, 448)
        text = "You can expect rain in the morning, with partly cloudy in the afternoon."
        lines = impression.wrap(c, text, "regular", 14, [440, 584])
        self.assertEqual(" ".join(lines), text)
        self.assertEqual(len(lines), 2)
        lines = impression.wrap(c, text * 3, "regular", 14, [440, 584])
        self.assertTrue(lines[-1].endswith("…"))  # too long even for two lines

    def test_alert_banner_keeps_the_full_name(self):
        long_alert = copy.deepcopy(SAMPLE)
        long_alert["alerts"] = [{"event": "Hurricane Force Wind Warning", "start": 0, "end": SAMPLE["current"]["dt"] + 86400},
                                {"event": "Coastal Flood Advisory", "start": 0, "end": SAMPLE["current"]["dt"] + 86400}]
        c = impression.ImpressionCanvas(600, 448)
        fc = impression.Forecast(long_alert, self.NOW, hours=24, days=7)
        drawn = []
        with mock.patch.object(impression, "draw_banner", lambda c, title, detail, fill: drawn.append((title, detail))):
            impression.draw_footer(c, fc, "imperial", self.T, False, self.NOW, None)
        self.assertEqual(drawn, [("⚠ Hurricane Force Wind Warning", "Until Thu 7 AM · also Coastal Flood Advisory")])
        self.assertIn(impression.RED, self.render(long_alert))

    def test_uses_the_wider_forecast(self):
        fc = common.Forecast(SAMPLE, self.NOW, hours=24, days=7)
        self.assertEqual(len(fc.hours), 24)
        self.assertEqual([fc.local(d["dt"]).strftime("%a") for d in fc.next_days],
                         ["Thu", "Fri", "Sat", "Sun", "Mon", "Tue", "Wed"])

    def test_bands_and_words(self):
        I = impression
        self.assertEqual([I.temp_ink(t, "imperial") for t in (32, 40, 41, 59, 60, 74, 75, 84, 85, 100)],
                         [I.BLUE, I.BLUE, I.GREEN, I.GREEN, I.YELLOW, I.YELLOW, I.ORANGE, I.ORANGE, I.RED, I.RED])
        self.assertEqual([I.temp_ink(t, "metric") for t in (0, 10, 20, 27, 31)], [I.BLUE, I.GREEN, I.YELLOW, I.ORANGE, I.RED])
        self.assertEqual(I.band_edges("imperial"), [40.5, 59.5, 74.5, 84.5])
        self.assertEqual([impression.uv_style(u)[2] for u in (0, 3, 6, 8, 11)], ["Low", "Moderate", "High", "Very high", "Extreme"])
        self.assertEqual([common.compass(d) for d in (0, 90, 290, 350)], ["N", "E", "WNW", "N"])
        self.assertEqual([common.moon_name(p) for p in (0, 0.25, 0.4, 0.5, 0.75, 0.99)],
                         ["New moon", "First quarter", "Waxing gibbous", "Full moon", "Last quarter", "New moon"])
        self.assertEqual(impression.rain_amount(4.2, "imperial"), "0.17 in")
        self.assertEqual(impression.pressure_text(1014, "imperial"), "29.94 in")
        self.assertEqual(impression.pressure_trend(common.Forecast(SAMPLE, self.NOW, hours=24)), "falling")


if __name__ == "__main__":
    unittest.main()
