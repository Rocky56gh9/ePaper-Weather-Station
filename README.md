# ePaper Weather Station

A small, always-on weather display you can mount anywhere. A Raspberry Pi Zero pulls current conditions and a 3-day forecast from OpenWeather every 15 minutes and draws them on a Waveshare 3.52" e-Paper screen. E-paper holds its image with no power, so the screen stays readable between updates and stays readable if the Pi loses its network connection.

<p>
  <img src="https://github.com/user-attachments/assets/b574e333-42d7-4eb8-a791-5b9926c1b199" alt="The weather station mounted on a wall" width="45%">
  <img src="docs/preview.png" alt="Screen layout rendered from sample data" width="45%">
</p>

## What you need

| Part | Notes |
| --- | --- |
| Raspberry Pi Zero W or Zero 2 W | Any Pi with a 40-pin header and Wi-Fi works. |
| microSD card, 8 GB or larger | |
| [Waveshare 3.52" e-Paper HAT](https://www.waveshare.com/3.52inch-e-paper-hat.htm) | Monochrome, 360 × 240. Plugs straight onto the GPIO header. |
| OpenWeather account | Free. See step 1. |
| Case | Optional. The Adafruit Pi Zero case fits. |

## Setup

### 1. Get an OpenWeather API key

1. Create a free account at [openweathermap.org](https://home.openweathermap.org/users/sign_up).
2. Subscribe to **One Call API 3.0**. OpenWeather asks for a card, but the first 1,000 calls per day are free and this station makes 97. To guarantee you're never billed, set your daily call limit to 1,000 under **Billing plans**.
3. Copy your key from [API keys](https://home.openweathermap.org/api_keys). New keys can take a couple of hours to activate.

### 2. Flash the SD card

1. In [Raspberry Pi Imager](https://www.raspberrypi.com/software/), choose **Raspberry Pi OS Lite**.
2. Open the OS customization settings. Set a hostname, username, and password, enter your Wi-Fi details, and enable SSH.
3. Write the card, put it in the Pi, attach the display, and power up. Give it a few minutes to join your network.

### 3. Install

SSH in, using the hostname you chose:

```sh
ssh your-username@your-hostname.local
```

Then run:

```sh
sudo apt install -y git
git clone https://github.com/Rocky56gh9/ePaper-Weather-Station.git
cd ePaper-Weather-Station
./install.sh
```

The installer:

- installs the Python packages from Raspberry Pi OS,
- enables SPI,
- asks for your API key, latitude, longitude, and units, and saves them to `config.ini`,
- schedules an update every 15 minutes and a deep clean at 1:10am,
- draws the first forecast.

If it just enabled SPI, it asks you to reboot first. The display then updates within 15 minutes.

To find your coordinates, right-click your location in Google Maps and click the numbers at the top of the menu to copy them.

## Using it

| Task | Command |
| --- | --- |
| Update the display now | `python3 weather_station.py` |
| Clear ghosting manually | `python3 weather_station.py --deep-clean` |
| View logs | `journalctl -t epaper-weather` |
| Change your key, location, or units | `nano config.ini` |
| Get the latest version | `git pull` |

The nightly deep clean cycles every pixel black and white twice. That clears the faint ghosting e-paper builds up from showing the same lines and labels all day.

If an update fails (no network, or an OpenWeather outage), the display keeps the last good forecast. The **Last updated** time at the bottom shows how old it is.

## Customizing the layout

Try layout changes on your computer first. No Pi or API key needed:

```sh
pip install pillow requests
python3 weather_station.py --demo --preview preview.png
```

`--demo` uses `sample_data.json` instead of calling OpenWeather, and `--preview` saves the screen as a PNG. Positions and font sizes live in `render()` in `weather_station.py`. The canvas is 360 × 240 pixels, and black and white are the only colors.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `OpenWeather rejected the API key (401)` | Check that your account has the **One Call API 3.0** subscription, not only the free current-weather API. New keys can take a couple of hours to activate. |
| `No such file or directory: '/dev/spidev0.0'` | SPI is off. Run `sudo raspi-config nonint do_spi 0`, then reboot. |
| Display never changes | Check that the HAT is fully seated on all 40 pins, then run `python3 weather_station.py` and read the output. |
| `config.ini not found` | Run `./install.sh`, or `cp config.example.ini config.ini` and edit it. |

## Project layout

```
weather_station.py   fetches the forecast and draws the screen
install.sh           one-time setup on the Pi
config.example.ini   settings template (config.ini is created from it and git-ignored)
sample_data.json     sample data for --demo
waveshare_epd/       Waveshare's display driver, unmodified (MIT, see file headers)
fonts/               DejaVu Sans (free license, see fonts/LICENSE)
```

## License

MIT. See [LICENSE](LICENSE). The bundled Waveshare driver and DejaVu fonts keep their own licenses.
