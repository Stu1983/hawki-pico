#!/bin/bash
# First install onto a Pico 2 W over USB (after flashing MicroPython - see README).
# Needs mpremote:  pip install mpremote
# Usage: tools/install.sh [device]     e.g. tools/install.sh /dev/ttyACM0  (default: auto)
set -e
cd "$(dirname "$0")/../firmware"
DEV=${1:+connect $1}
mpremote $DEV fs cp *.py *.html ca.pem : + reset
echo "Done. The Pico restarts and opens a Wi-Fi network called HAWKi-Setup-XXXX (password: oiltanks)."
echo "Join it and browse to http://192.168.4.1/ to pick your home Wi-Fi."
