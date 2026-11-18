# hawki-pico

A home-made receiver for **Magnus HAWKi** oil-tank monitors, built on a **Raspberry Pi Pico 2 W**.
It works without the subscription gateway or the phone app.

The Pico listens for the monitors' Bluetooth broadcasts, turns each reading into litres, and runs a small web page on your home Wi-Fi:

- **Tanks.** Each tank shows litres, % full, battery and signal. Add a tank by picking its monitor from the list of sensors nearby (a new Pico opens on that list).
- **Tank shapes.** Rectangular, horizontal or vertical cylinder. Rectangular tanks with "windows" (holes through the tank) use either the same maths as the Magnus app or your own rough measurements, drawn to scale as you type them.
- **More than one tank.** Each tank is *In use* (the one you're drawing from: counted, and warned about), *Standby* (valve shut, oil waiting) or *Off*. Two monitors on the same tank can be linked with *Same tank as*, so they share the tank's size, heights and capacity.
- **Dashboard.** The oil left (with the unusable oil below the outlet in brackets), litres a day with a 30-day chart, the weeks left, and the oil level with its forecast.
- **History and forecast.** One reading an hour for 2 years, then one a day after that (about 110 KB per tank). Deliveries are found by themselves. Usage by month is shown as an oil year (July to June) against an average year, with "order by" and "could run dry" dates:
  - with a previous year of your own readings, the forecast follows your own use at that time of year, scaled to how this year is running;
  - before that, from a *typical year's oil* if you enter one (say, last year's deliveries), spread over the year by your town's usual weather and scaled by how this winter is going; without one, from your last two weeks' use and the weather;
  - hot water is measured from your own summer use when there is one, a bit more in winter because mains water is colder.
- **Weather.** Pick your town and the Pico fetches the daily temperature from Open-Meteo, to compare your use with the weather and to shape the forecast.
- **Alerts.** Phone notifications through ntfy (free) or Pushover when a tank in use reaches its reorder level, oil drops faster than the boiler can burn it (a leak or theft), a monitor's battery is low, or a monitor has sent no new reading for 6 hours. Most wait for the reading to hold (a low level for over an hour, for example), so one odd reading doesn't set them off.
- **Costs.** Record the supplier and price for each delivery to track pence per litre, money spent and running cost. In Northern Ireland, today's oil prices from cheapestoil.co.uk can be shown alongside.
- **Home Assistant (optional).** Built in over MQTT: Home Assistant finds each tank by itself (MQTT discovery), with litres, %, battery, the order-by date and more. (`tools/ha-bridge.sh` is the older way, from a separate computer.)
- **Backup.** Export and import the tanks, deliveries and readings (not the Wi-Fi, PIN or alert settings), or export the readings as CSV.
- **Updates.** Press *Check for updates* on the page to install new releases from this repo.
- **A PIN.** Changing settings needs the admin PIN; looking doesn't.

## What it connects to

Only what you switch on, plus the clock. From the Pico:

- the clock: `pool.ntp.org` or `time.google.com`, when it joins your Wi-Fi (and until the clock is set);
- updates: `raw.githubusercontent.com`, only when someone checks for or installs an update;
- weather: Open-Meteo, once you've picked a town: daily temperatures for that place's coordinates, and its forecast every few hours;
- oil prices: `cheapestoil.co.uk`, once a day if switched on (with your BT postcode district, if you give one), trying again later if it fails;
- alerts: ntfy or Pushover, when an alert or a test message is sent (with your Pushover keys, if that's what you use);
- Home Assistant: the MQTT broker you set up (normally Home Assistant on your own network; the connection isn't encrypted, so keep it local).

From your browser, while you're on the page: searching for your town sends what you type to Open-Meteo's place search, and the page asks `postcodes.io` for the postcode district near that town (to suggest one for oil prices).

Nothing else leaves your network. Your Wi-Fi password and PIN never leave the Pico.

## What you need

- A Raspberry Pi Pico 2 W, plus a USB cable and power supply. Put it within Bluetooth range of the tanks and in reach of your Wi-Fi; a garage or outbuilding usually works.
- One or more Magnus HAWKi monitors that are already fitted.

## First install

1. **Flash MicroPython.** Download the Pico 2 W firmware (`RPI_PICO2_W`, v1.29 or newer) from <https://micropython.org/download/RPI_PICO2_W/>. Hold BOOTSEL while you plug the Pico in, then copy the `.uf2` file onto the drive that appears.
2. **Copy this project onto the Pico.** From a copy of this repository, on a computer with Python and Bash (Mac, Linux, or WSL on Windows), run:
   ```
   pip install mpremote
   tools/install.sh
   ```
3. **Connect it to your Wi-Fi.** The Pico opens a Wi-Fi network called **HAWKi-Setup-XXXX** (password `oiltanks`). Join it from a phone: the setup page opens by itself on most phones (otherwise browse to <http://192.168.4.1/>). It walks you through choosing a PIN and picking your home Wi-Fi, tries the Wi-Fi while you wait (a wrong password is usually reported straight away), and shows the Pico's address on your Wi-Fi. Take a screenshot of that address, or press and hold it to copy it, before you tap *Finish*: the setup window closes when the setup Wi-Fi switches off.
4. **Open the page.** Once your phone is back on your home Wi-Fi, open <http://hawki-pico.local/> (works on most computers and iPhones) or the address it showed. After the restart it can take a minute or so to answer at first. Then add your tanks from the sensors listed.

**Keep the address the same.** Either reserve the Pico's address in your router (look for "DHCP reservation" or "fixed IP", with the MAC address shown under Config), or set a fixed address on the Pico itself (**Config → Wi-Fi & network**, *Change* next to *Address*). Keep that settings page open while it switches: the new address is tried for one start only, and kept once the page has reached the Pico at it. If that doesn't happen within 3 minutes, the Pico goes back to the old settings by itself. You can also change the name it uses on the network (`hawki-pico`).

**Tank height** is the *maximum fill height*: from the bottom of the monitor down to the top of the outlet pipe. That's what the Magnus app asks for too.

## On your phone

These work while your phone is on your home Wi-Fi (the Pico isn't reachable from outside; alerts reach you anywhere).

**An app icon.** In Safari, open the monitor's page (<http://hawki-pico.local/>), tap *Share*, then *Add to Home Screen*. It opens full screen like an app. Sign in with the PIN once in it (it keeps its own sign-in, apart from Safari's). On Android, Chrome's menu has *Add to Home screen*.

**A widget showing the oil left (iPhone, iPad).** The free [Scriptable](https://apps.apple.com/app/scriptable/id1405459188) app runs `tools/hawki-widget.js`, which shows the oil left, % full, the order-by date (amber three weeks ahead, red one week ahead) and how old the reading is. Away from home it shows the last figures it had, marked "as of". Tapping it opens the monitor's page.

1. Install **Scriptable** from the App Store.
2. In Safari, open <https://raw.githubusercontent.com/Stu1983/hawki-pico/main/tools/hawki-widget.js>, select all the text and copy it.
3. In Scriptable, tap **+**, paste, and tap the title at the top to name it **Oil**.
4. At home, tap **▶** to try it. Allow it to find devices on your local network when iOS asks. You should see the widget.
5. On the home screen, press and hold an empty space, tap **Edit** (or **+**), choose **Scriptable**, pick the small or medium size and **Add Widget**. Press and hold the new widget, **Edit Widget**, and set **Script** to **Oil**. If the monitor isn't at `hawki-pico.local`, put its address (e.g. `http://192.168.1.57`) in **Parameter**.
6. For the lock screen: press and hold the lock screen, **Customize**, tap the widget area, add **Scriptable** (the wide one is best) and choose **Oil** the same way.

iOS decides how often a widget refreshes (usually every 15 to 30 minutes). The order-by date appears once the dashboard has been opened, since it's worked out there.

## Updates

**Software → Check for updates** on the Pico's page compares its version with the latest release here. If there's a newer one, **Install**:

- **Download and check.** The Pico downloads the release over HTTPS, checks GitHub's certificate, checks the release's signature, and checks every file against the SHA-256 listed in its `manifest.json`. If anything doesn't match, nothing is changed.
- **Install and restart.** It swaps the files in, keeps the old ones, and restarts. If it's too short of memory to download, it restarts first and tries again straight after.
- **Automatic rollback.** A new version has 10 minutes to prove itself: back on your Wi-Fi, with its web server answering. If it crashes or can't, the Pico puts the old version back by itself and the page says so. Once it has proved itself (after 2 minutes, usually), it's kept.

Nothing updates without someone pressing the button. Updates never replace `main.py`, `rescue.py` or `rollback.py`, so the recovery path stays intact. A Pico first installed with 1.0.x needs `tools/install.sh` run once over USB to get the 1.1 start-up files; until then it refuses further updates and says so.

### Making a release (maintainers)

```
python3 tools/release.py X.Y.Z "What changed, in a sentence or two"   # runs the tests, signs manifest.json
git add -A && git commit -m "Release vX.Y.Z: ..." && git tag vX.Y.Z
python3 tools/release.py --check vX.Y.Z                                # the tag matches its signed manifest
git push origin main vX.Y.Z
```

`release.py` sets `firmware/version.py` and writes `manifest.json` with each file's hash and size, signed with the release key. Picos read `manifest.json` from `main` and download the files from the tag it names.

## If something goes wrong

- **Restart.** **Config → Software → Restart the Pico**, for one that's out of reach. It also restarts by itself if it keeps running out of memory.
- **Forgot the PIN, or a fixed address that doesn't work.** Hold the Pico's BOOTSEL button for 5 seconds while it's running: the PIN is cleared (set a new one within 30 minutes) and the address goes back to automatic.
- **Lost Wi-Fi.** Whenever it isn't on your Wi-Fi (after its first minute running), the setup network **HAWKi-Setup-XXXX** comes up so you can put it right.
- **Rescue mode.** If the app can't start (and it isn't a fresh update to roll back), `main.py` starts `rescue.py`: a minimal server that stays on your Wi-Fi, or opens **HAWKi-Rescue** (password `oiltanks`), so new files can still be uploaded with the maintenance token (in rescue mode the token alone is enough).
- **Maintenance token.** It's in the Pico's `config.json` (read it over USB with `mpremote fs cat :config.json`). While the app is running, uploading files over Wi-Fi (`curl -T app.py "http://PICO/file?name=app.py&t=TOKEN"`) only works with **maintenance access** switched on under **Config → Software**; it's off by default.

## How it works

- **Readings.** HAWKi monitors broadcast ordinary (legacy) BLE adverts every few seconds. The 10-byte manufacturer-data field packs the distance from the sensor to the oil in mm, plus battery, temperature, a float flag, error bits and firmware version. `firmware/hawki_decode.py` unpacks them, and `tests/test_decode.py` holds a reading confirmed against the Magnus app.
- **Listening.** A HAWKi measures once an hour, at its own fixed minute, and repeats that reading in every broadcast until the next one. The Pico works out each sensor's minute and listens from just before it until the new reading arrives (`firmware/listen.py`). For the rest of the hour the shared radio is left to Wi-Fi (unless a sensor's reading is overdue). It listens passively, so the sensors aren't asked for anything extra; only while it's looking for new sensors (the first minutes after starting, while it has no tanks, or while **Sensors nearby** is open) does it ask them for their names. Each new reading is saved with the time it was heard.
- **Litres.** `firmware/tankcalc.py` turns distance into litres. Its "standard" model for rectangular tanks with windows reproduces the Magnus app's figures to within 1 L.
- **History.** Stored as 6-byte records (time, mm) in `h_<sensor>.bin`. History keeps distances, not litres, so changing a tank's shape re-draws all past readings.
- **Wi-Fi.** On a home network with several access points (mesh, extenders), the Pico picks the strongest it hears and stays on it (unless another becomes much stronger), rather than whichever it hears first. If that one keeps failing, every third try it takes any.

## Tests

```
for t in tests/test_*.py; do python3 $t; done
node tests/tests_forecast.js                                  # the forecast, no packages needed
node tests/test_pages_parse.js firmware/                      # every page script parses
NODE_PATH=... node tests/tests_setup_page.js firmware/        # page tests like this one need jsdom
```

`tools/release.py` runs the Python tests, the forecast tests and the parse check before it will make a release.

This project is independent and not affiliated with Magnus Monitors. MIT licence.
