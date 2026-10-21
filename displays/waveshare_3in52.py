"""Waveshare 3.52" e-Paper HAT (360x240, black and white), via the bundled waveshare_epd driver."""


def show(image, deep_clean=False):
    from waveshare_epd import epd3in52

    # Palette index 0 is white; everything else (black, and accent mapped to black) is ink
    bw = image.point(lambda index: 255 if index == 0 else 0, "1") if image.mode == "P" else image.convert("1")

    epd = epd3in52.EPD()
    try:
        epd.init()
        if deep_clean:
            # Full black/white cycles exercise every pixel and clear ghosting from the static layout
            frame_bytes = epd.width * epd.height // 8
            for _ in range(2):
                for fill in (0x00, 0xFF):
                    epd.send_command(0x13)  # start frame data
                    epd.send_data2([fill] * frame_bytes)
                    epd.lut_GC()
                    epd.refresh()
        epd.display(epd.getbuffer(bw))
        epd.lut_GC()
        epd.refresh()
    finally:
        epd.sleep()  # cuts panel power; leaving it powered can damage the display
