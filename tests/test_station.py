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
import layout  # noqa: E402
import weather_station as ws  # noqa: E402
from displays import SCREENS  # noqa: E402

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

    def test_inky_screen_renders_at_its_size(self):
        write_config(self.config, screen="inky_what", rotate="180")
        self.assertEqual(ws.main([]), 0)
        screen, image = self.last
        self.assertEqual(screen, "inky_what")
        self.assertEqual(image.size, (400, 300))

    def test_quiet_hours(self):
        hour = datetime.now().hour
        write_config(self.config, quiet=f"{hour}-{(hour + 1) % 24}")
        self.assertEqual(ws.main([]), 0)
        self.assertEqual(self.shown, [])
        self.assertEqual(ws.main(["--deep-clean"]), 0)  # the scheduled deep clean still runs
        self.assertEqual(self.shown, [True])


class LayoutTests(unittest.TestCase):
    def test_screen_sizes_and_accent(self):
        stormy = copy.deepcopy(SAMPLE)
        stormy["alerts"] = [{"event": "Flood Warning", "start": 0, "end": SAMPLE["current"]["dt"] + 86400}]
        for screen, (width, height, accent) in SCREENS.items():
            image = layout.render(stormy, "imperial", self.T, self.NOW, size=(width, height), accent=accent)
            self.assertEqual(image.size, (width, height))
            used = {index for _, index in image.getcolors()}
            # Red screens use the accent ink for rain and alerts; black-and-white screens never do
            self.assertEqual(layout.ACCENT in used, accent is not None, screen)


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


if __name__ == "__main__":
    unittest.main()
