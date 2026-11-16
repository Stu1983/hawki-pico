# hawki-pico

A home-made receiver for **Magnus HAWKi** oil-tank monitors, built on a **Raspberry Pi Pico 2 W**.
It works without the subscription gateway or the phone app.

The Pico listens for the monitors' Bluetooth broadcasts, turns each reading into litres, and runs a small web page on your home Wi-Fi:

- **Tanks.** Each tank shows litres, % full, battery and signal. Add a tank by picking its monitor from the list of sensors nearby.
- **Tank shapes.** Rectangular, horizontal or vertical cylinder. Rectangular tanks with "windows" (holes through the tank) use either the same maths as the Magnus app or your own rough measurements, drawn to scale as you type them.
- **History and forecast.** The Pico keeps one reading an hour for 2 years, then one a day after that, for about 110 KB per tank. It detects deliveries and shows usage by month for each year. "Order by" and "could run dry" dates follow the heating season. Once you have a previous year, they use your own usage from that time of year. Until then:
  - hot water is your own summer usage (from a June to August month with the heating off), up to 25% more in winter because mains water is colder;
  - heating follows a typical UK year, sized to your recent use. Before a summer of your own data, hot water is taken as 15% of the year's oil.
- **Dashboard.** It opens on one tank (pick which under **Tanks**, if you have more than one). It shows:
  - the oil left, with the unusable oil below the outlet in brackets;
  - litres a day, with a 30-day chart;
  - the weeks left;
  - the oil level, with the forecast.

  **Config** holds the nearby sensors, Wi-Fi, network name, security, updates and backup.
- **Costs.** Record the supplier and price per delivery to track p/L, money spent and running cost.
- **Backup.** Export and import everything (settings, deliveries, readings), or export the readings as CSV.
- **Updates.** Press *Check for updates* on the page to install new releases from this repo.
- **Home Assistant (optional).** `tools/ha-bridge.sh` posts litres, %, distance and battery to Home Assistant every minute.

Nothing is sent anywhere except to GitHub, and only when you check for updates.

## What you need

- A Raspberry Pi Pico 2 W, plus a USB cable and power supply. Put it within Bluetooth range of the tanks and in reach of your Wi-Fi; a garage or outbuilding usually works.
- One or more Magnus HAWKi monitors that are already fitted.

## First install

1. **Flash MicroPython.** Download the Pico 2 W firmware (`RPI_PICO2_W`, v1.29 or newer) from <https://micropython.org/download/RPI_PICO2_W/>. Hold BOOTSEL while you plug the Pico in, then copy the `.uf2` file onto the drive that appears.
2. **Copy this project onto the Pico.** On any computer with Python, run:
   ```
   pip install mpremote
   tools/install.sh
   ```
3. **Connect it to Wi-Fi.** The Pico opens a Wi-Fi network called **HAWKi-Setup-XXXX** (password `oiltanks`). Join it, browse to <http://192.168.4.1/> and pick your home Wi-Fi.
4. **Open the page.** Browse to the Pico's address; your router shows it, or try <http://hawki-pico.local/>. Then add your tanks.

   **Keep the address the same.** Reserve the address for the Pico in your router: look for "fixed IP" or "DHCP reservation", and use the MAC address shown under Config. The Pico has no static-IP setting of its own: on this firmware, a fixed address set on the Pico itself didn't survive a Wi-Fi reconnect. You can change the name it shows on the network under Config.

**Tank height** is the *maximum fill height*: from the bottom of the monitor down to the top of the outlet pipe. That's what the Magnus app asks for too.

## Updates

**Software → Check for updates** on the Pico's page compares its version with the latest release here. If there's a newer one, **Install**:

- **Download and check.** The Pico downloads the release over HTTPS, checks GitHub's certificate, and checks every file against the SHA-256 listed in the release's `manifest.json`. If anything doesn't match, nothing is changed.
- **Install and restart.** It swaps the files in, keeps the old ones, and restarts.
- **Automatic rollback.** If the new version crashes, or can't get back onto your Wi-Fi within 10 minutes, the Pico puts the old version back by itself and the page says so.

Nothing updates without someone pressing the button. `main.py`, `rescue.py` and `rollback.py` are never replaced over the air, so the recovery path always stays intact. A Pico first installed with 1.0.x needs `tools/install.sh` run once over USB to get the 1.1 start-up files; until then it refuses further updates and says so.

### Making a release (maintainers)

```
python3 tools/release.py 1.0.1 "What changed, in a sentence or two"
git add -A && git commit -m "Release v1.0.1" && git tag v1.0.1 && git push origin main v1.0.1
```

`release.py` runs the tests, sets `firmware/version.py`, and writes `manifest.json` with each file's hash and size. Picos read `manifest.json` from `main` and download the files from the tag.

## If something goes wrong

- **Rescue mode.** If the app can't start (and it isn't a fresh update to roll back), `main.py` starts `rescue.py`. Rescue mode is a minimal server that stays on your Wi-Fi, or opens **HAWKi-Rescue** (password `oiltanks`), so new files can still be uploaded.
- **Maintenance token.** Uploads need the token stored in the Pico's `config.json`. Read it over USB with `mpremote fs cat :config.json`. With the token you can also upload files over Wi-Fi, e.g. `curl -T app.py "http://PICO/file?name=app.py&t=TOKEN"`.

## How it works

- **Readings.** HAWKi monitors broadcast ordinary (legacy) BLE adverts every few seconds. The 10-byte manufacturer-data field packs the distance from the sensor to the oil in mm, plus battery, temperature, a float flag, error bits and firmware version. `firmware/hawki_decode.py` unpacks them, and `tests/test_decode.py` holds a reading confirmed against the Magnus app.
- **Litres.** `firmware/tankcalc.py` turns distance into litres. Its "standard" model for rectangular tanks with windows reproduces the Magnus app's figures to within 1 L.
- **History.** Stored as 6-byte records (time, mm) in `h_<sensor>.bin`. History keeps distances, not litres, so changing a tank's shape re-draws all past readings.

## Tests

```
for t in tests/test_*.py; do python3 $t; done
node tests/tests_forecast.js                                  # seasonal model, no packages needed
NODE_PATH=... node tests/tests_hist.js firmware/hist.html     # needs jsdom
```

This project is independent and not affiliated with Magnus Monitors. MIT licence.
