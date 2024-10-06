import sys
import os
import requests
import time
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime as dt
import traceback

# Library and picture directories
libdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'lib')
picdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'pic')
if os.path.exists(libdir):
    sys.path.append(libdir)

from waveshare_epd import epd3in52  # Import the correct driver for the 3.52-inch display

# OpenWeather API configuration
API_KEY = "YOUR_OPENWEATHER_API_KEY"
LAT, LON = "YOUR_LATITUDE", "YOUR_LONGITUDE"

def fetch_weather_data():
    try:
        print("Fetching weather data...")
        current_url = f"https://api.openweathermap.org/data/2.5/weather?lat={LAT}&lon={LON}&appid={API_KEY}&units=imperial"
        forecast_url = f"https://api.openweathermap.org/data/2.5/onecall?lat={LAT}&lon={LON}&exclude=minutely,alerts&appid={API_KEY}&units=imperial"

        current_response = requests.get(current_url)
        forecast_response = requests.get(forecast_url)

        if current_response.status_code == 200 and forecast_response.status_code == 200:
            return current_response.json(), forecast_response.json()
        else:
            print(f"Error fetching data from OpenWeather: {current_response.status_code}, {forecast_response.status_code}")
            return None, None
    except Exception as e:
        print("Error in fetch_weather_data: ", e)
        return None, None

def draw_text(draw, text, position, font):
    try:
        print(f"Drawing text: {text}")
        draw.text(position, text, font=font, fill=0)  # 0 for black text
    except Exception as e:
        print("Error in draw_text: ", e)

def draw_wrapped_text(draw, text, position, font, max_width, max_height):
    try:
        words = text.split()
        lines = []
        line = ''
        line_height = font.getsize('A')[1]
        y_offset = position[1]
        max_lines = max_height // line_height

        for word in words:
            test_line = f"{line} {word}".strip()
            w, h = draw.textsize(test_line, font=font)
            if w <= max_width:
                line = test_line
            else:
                lines.append(line)
                line = word
                if len(lines) == max_lines:
                    break
        if line:
            lines.append(line)

        for line in lines[:max_lines]:
            if y_offset + line_height > position[1] + max_height:
                break
            draw.text((position[0], y_offset), line, font=font, fill=0)
            y_offset += line_height
    except Exception as e:
        print("Error in draw_wrapped_text: ", e)

def draw_horizontal_line(draw, x_start, y, length, thickness):
    try:
        x_end = x_start + length
        draw.line((x_start, y, x_end, y), fill=0, width=thickness)
    except Exception as e:
        print("Error in draw_horizontal_line: ", e)

def draw_vertical_line(draw, x, y_start, length, thickness):
    try:
        y_end = y_start + length
        draw.line((x, y_start, x, y_end), fill=0, width=thickness)
    except Exception as e:
        print("Error in draw_vertical_line: ", e)

def main():
    try:
        print("Initializing the ePaper display...")
        epd = epd3in52.EPD()
        epd.init()
        epd.Clear()

        print("Setting up fonts...")
        font_title = ImageFont.truetype(os.path.join(picdir, 'DejaVuSans-Bold.ttf'), 25)
        font_text = ImageFont.truetype(os.path.join(picdir, 'DejaVuSans.ttf'), 21)
        font_update = ImageFont.truetype(os.path.join(picdir, 'DejaVuSans.ttf'), 12)

        print("Fetching and displaying weather data...")
        current_weather_data, forecast_weather_data = fetch_weather_data()
        if current_weather_data and forecast_weather_data:
            image = Image.new('1', (epd.height, epd.width), 255)  # 255 for white background
            draw = ImageDraw.Draw(image)

            # Now conditions
            draw_text(draw, "Now", (0, 0), font_title)
            current_temp = f"{int(current_weather_data['main']['temp'])}°F"
            draw_text(draw, current_temp, (0, 30), font_text)

            # Today conditions
            draw_text(draw, "Today", (100, 0), font_title)
            today_high = f"High: {int(forecast_weather_data['daily'][0]['temp']['max'])}°F"
            today_low = f"Low: {int(forecast_weather_data['daily'][0]['temp']['min'])}°F"
            draw_text(draw, today_high, (100, 30), font_text)
            draw_text(draw, today_low, (225, 30), font_text)
            today_conditions = forecast_weather_data['daily'][0]['weather'][0]['description'].capitalize()
            draw_text(draw, today_conditions, (100, 60), font_text)

            # Tomorrow conditions
            draw_text(draw, "Tomorrow", (0, 95), font_title)
            tomorrow_high = f"High: {int(forecast_weather_data['daily'][1]['temp']['max'])}°F"
            tomorrow_low = f"Low: {int(forecast_weather_data['daily'][1]['temp']['min'])}°F"
            draw_text(draw, tomorrow_high, (0, 125), font_text)
            draw_text(draw, tomorrow_low, (0, 150), font_text)
            tomorrow_conditions = forecast_weather_data['daily'][1]['weather'][0]['description'].capitalize()
            # Wrap the conditions text within specified limits
            draw_wrapped_text(draw, tomorrow_conditions, (0, 175), font_text, max_width=170, max_height=45)

            # Next Day conditions
            draw_text(draw, "Next Day", (180, 95), font_title)
            next_day_high = f"High: {int(forecast_weather_data['daily'][2]['temp']['max'])}°F"
            next_day_low = f"Low: {int(forecast_weather_data['daily'][2]['temp']['min'])}°F"
            draw_text(draw, next_day_high, (180, 125), font_text)
            draw_text(draw, next_day_low, (180, 150), font_text)
            next_day_conditions = forecast_weather_data['daily'][2]['weather'][0]['description'].capitalize()
            # Wrap the conditions text within specified limits
            draw_wrapped_text(draw, next_day_conditions, (180, 175), font_text, max_width=170, max_height=45)

            # Last Updated
            last_updated = dt.now().strftime("%-m/%-d/%Y %-I:%M")
            draw_text(draw, f"Last Updated: {last_updated}", (epd.width // 2 - 50, 225), font_update)

            # Draw lines to define sections
            draw_horizontal_line(draw, x_start=0, y=90, length=360, thickness=2)
            draw_vertical_line(draw, x=85, y_start=0, length=90, thickness=2)
            draw_vertical_line(draw, x=175, y_start=90, length=120, thickness=2)

            print("Displaying the image on ePaper...")
            epd.display(epd.getbuffer(image))
            epd.refresh()
            time.sleep(2)

        else:
            print("Failed to fetch weather data.")

        print("Putting the display to sleep...")
        epd.sleep()

    except Exception as e:
        print("Error in main: ", e)
        traceback.print_exc()
        try:
            epd.sleep()
        except:
            pass

    except KeyboardInterrupt:
        print("Script interrupted by user")
        epd3in52.epdconfig.module_exit()
        exit()

if __name__ == "__main__":
    main()
