"""Supported screens. Each driver module provides show(image, deep_clean=False), where image is
a palette image from layouts.render() at the screen's size, in the panel's own ink order. Drivers
import their hardware libraries inside show(), so previews work on any machine."""
import importlib
from collections import namedtuple

# size: (width, height). layout: module in layouts/. accent: the compact layout's third ink, if any.
Screen = namedtuple("Screen", "size layout accent")

SCREENS = {
    "waveshare_3in52": Screen((360, 240), "compact", None),
    "inky_what": Screen((400, 300), "compact", "red"),
    "inky_impression_5in7": Screen((600, 448), "impression", None),
}


def show(screen, image, deep_clean=False):
    importlib.import_module(f"displays.{screen}").show(image, deep_clean=deep_clean)
