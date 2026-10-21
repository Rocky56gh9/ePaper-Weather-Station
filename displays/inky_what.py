"""Pimoroni Inky wHAT (400x300; black/white, or black/white plus red or yellow), via Pimoroni's inky library."""
from PIL import Image

WHITE, BLACK, ACCENT = 0, 1, 2


def show(image, deep_clean=False):
    from inky.auto import auto

    display = auto()  # identifies the board from its EEPROM
    if display.colour not in ("red", "yellow"):
        # Black-and-white board: draw accents in black
        image = Image.frombytes("P", image.size, image.tobytes().replace(bytes([ACCENT]), bytes([BLACK])))

    if deep_clean:
        # Solid fills in every ink clear ghosting; colored inks ghost more than black
        inks = (ACCENT, BLACK, WHITE) if display.colour in ("red", "yellow") else (BLACK, WHITE)
        for _ in range(2):
            for ink in inks:
                display.set_border(ink)
                display.set_image(Image.new("P", (display.width, display.height), ink))
                display.show()

    display.set_border(WHITE)
    display.set_image(image)
    display.show()
