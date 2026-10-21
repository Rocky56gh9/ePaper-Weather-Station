"""Supported screens. Each driver module provides show(image, deep_clean=False), where image is
a palette image from layout.render() at the screen's size. Drivers import their hardware
libraries inside show(), so previews work on any machine."""
import importlib

SCREENS = {
    # name: (width, height, accent color for previews and rendering)
    "waveshare_3in52": (360, 240, None),
    "inky_what": (400, 300, "red"),
}


def show(screen, image, deep_clean=False):
    importlib.import_module(f"displays.{screen}").show(image, deep_clean=deep_clean)
