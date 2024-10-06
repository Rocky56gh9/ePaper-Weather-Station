# ePaper-Weather-Station
This simple project creates a small weatherstation you can mount anywhere for at-a-glance forecast information.

# Equipment List
1. Raspberry Pi Zero
2. SD Card for Raspberry Pi
3. Waveshare 3.52" monochrome e-Paper screen
4. Adafruit Raspberry Pi Zero case (Optional)

# New Build Guide

1. **Obtain APIs**
   - Go to the respective websites for Reddit and OpenWeather and create an account.
   - Follow the instructions to obtain your API keys.

2. **Configure SD Card:**
   - Use the Raspberry Pi Imager.
   - Install RaspberryPi OS <b>(Legacy, 32-bit Lite) Bullseye</b>. NOTE: For the time being, I've only been able to replicate successful installs with this setup.
   - Set a hostname, ID, and unique password.
   - Add your network SSID and password.
   - Enable SSH on the second tab.

3. **Initial Setup:**
   - Insert the SD card into the Pi and power it up.
   - Wait ~10 minutes for it to appear on your network.
   - Log into your router, find the Pi, and note its IP address.

4. **SSH Login:**
   - Open Terminal and run:
   ```
   ssh {unit name}@{IP address}
   ```
   - Enter the password and follow prompts.
   - If necessary, reset the SSH keys with:
   ```sh
   ssh-keygen -R {RPi-IP-Address}
   ```
   or
   ```sh
   ssh-keygen - R {username.local}
   ```
# Adding Your Configurations
Gather the following information before updating the base script. Configure the script with your information.

API key
- OpenWeather: API Key
- Latitude and Longitude for your location

![IMG_0085](https://github.com/user-attachments/assets/b574e333-42d7-4eb8-a791-5b9926c1b199)
