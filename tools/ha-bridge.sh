#!/bin/bash
# HAWKi logger + Home Assistant bridge - run every minute from cron on any always-on Linux box.
# 1. Appends "epoch<TAB>json" of the Pico's /hawki output to the monthly log.
# 2. Posts every tank configured on the Pico (its web page) to Home Assistant via the REST
#    states API: litres/percent are computed on the Pico (tankcalc.py), so the web page and
#    HA always agree. No HA config needed; entities reappear within a minute after an HA restart.
# Needs curl and jq. Settings come from the environment or the lines below:
#   PICO  the Pico's address          HA    Home Assistant's address
#   TOKF  file holding a Home Assistant long-lived access token (Profile > Security)
#   LOGDIR  where the monthly logs go
# Example crontab line:  * * * * * PICO=http://192.168.1.50 HA=http://homeassistant.local:8123 /path/ha-bridge.sh
PICO=${PICO:-http://hawki-pico.local}
HA=${HA:-http://homeassistant.local:8123}
TOKF=${TOKF:-$HOME/.config/hawki/ha_token}
LOGDIR=${LOGDIR:-$HOME/hawki-logs}
OUT=$LOGDIR/log-$(date +%Y-%m).tsv
mkdir -p "$LOGDIR"
NOW=$(date +%s)

J=$(curl -sf -m 8 "$PICO/hawki") || { printf '%s\tERR\n' "$NOW" >> "$OUT"; exit 0; }
printf '%s\t%s\n' "$NOW" "$J" >> "$OUT"

[ -s "$TOKF" ] || exit 0
TOK=$(cat "$TOKF")
post() {  # entity json
  curl -s -m 5 -o /dev/null -X POST -H "Authorization: Bearer $TOK" \
    -H 'Content-Type: application/json' -d "$2" "$HA/api/states/$1"
}

echo "$J" | jq -c '.sensors as $s | (.tanks // {}) | to_entries[]
  | select(.value.level != null and .value.age != null and .value.age < 5400)
  | {sfx: (.key | gsub(":"; "") | .[8:]), t: .value, v: $s[.key]}' |
while read -r row; do
  sfx=$(jq -r .sfx <<<"$row")
  post "sensor.hawki_${sfx}_distance" "$(jq -c '{state: (.t.level|tostring), attributes: {
      unit_of_measurement: "mm", friendly_name: (.t.name + " distance to oil"),
      icon: "mdi:hydraulic-oil-level", mac: .t.mac, name: .v.name, battery: .v.battery,
      temperature_raw: .v.temperature, error_status: .v.errorStatus, firmware: .v.firmwareVersion,
      nearly_empty: .v.isNearlyEmpty, rssi: .v.rssi, raw: .v.raw,
      sensor_clock: (.v.timestamp|todate), last_heard: (.v.rx|todate)}}' <<<"$row")"
  if [ "$(jq -r '.t.litres != null' <<<"$row")" = true ]; then
    post "sensor.hawki_${sfx}_litres" "$(jq -c '{state: (.t.litres | round | tostring), attributes: {
        unit_of_measurement: "L", device_class: "volume_storage", friendly_name: (.t.name + " litres"),
        icon: "mdi:barrel", state_class: "measurement"}}' <<<"$row")"
    post "sensor.hawki_${sfx}_percent" "$(jq -c '{state: (.t.percent | tostring), attributes: {
        unit_of_measurement: "%", friendly_name: (.t.name + " level"), icon: "mdi:oil-level",
        state_class: "measurement"}}' <<<"$row")"
  fi
  post "sensor.hawki_${sfx}_battery" "$(jq -c '{state: (.t.battery|tostring), attributes: {
      unit_of_measurement: "%", device_class: "battery", friendly_name: (.t.name + " sensor battery")}}' <<<"$row")"
done
