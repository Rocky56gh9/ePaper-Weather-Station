"""Pimoroni Inky Impression 5.7" (600x448, 7 inks), via Pimoroni's inky library.

The image arrives as a palette image already in the panel's ink order (black, white, green, blue,
red, yellow, orange), so inky sends it as-is with no dithering.
"""
from PIL import Image

BLACK, WHITE = 0, 1
CLEAN = 7  # the panel's own clearing waveform


def show(image, deep_clean=False):
    from inky.auto import auto

    display = auto()  # identifies the board from its EEPROM
    if (display.width, display.height) != image.size:
        raise RuntimeError(
            f"Found a {display.width}x{display.height} Inky, but screen = inky_impression_5in7 draws 600x448. "
            "Check the screen setting in config.ini."
        )

    if deep_clean:
        # Every refresh on this panel already runs a full color-cycling waveform, so one pass of
        # black, white, and the clean waveform is enough to clear any ghosting. Each takes ~30s.
        for ink in (BLACK, WHITE, CLEAN):
            display.set_border(ink if ink != CLEAN else WHITE)
            display.set_image(Image.new("P", image.size, ink))
            display.show()

    display.set_border(WHITE)
    display.set_image(image)
    display.show()
