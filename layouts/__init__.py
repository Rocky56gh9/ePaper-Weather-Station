"""Screen layouts. Each module provides render(data, units, thresholds, now, size, accent,
evening_starts, offline_since) and returns a palette image ready for that screen's driver.

    compact      small 2- and 3-ink screens (Waveshare 3.52", Inky wHAT)
    impression   the 7-color Inky Impression 5.7": 24-hour chart, 7-day outlook, details grid
"""
import importlib

from displays import SCREENS


def render(screen, data, units, thresholds, now, evening_starts=18, offline_since=None):
    """Draw the screen named in displays.SCREENS. now and offline_since are timezone-aware datetimes."""
    profile = SCREENS[screen]
    module = importlib.import_module(f"layouts.{profile.layout}")
    return module.render(data, units, thresholds, now, size=profile.size, accent=profile.accent,
                         evening_starts=evening_starts, offline_since=offline_since)
