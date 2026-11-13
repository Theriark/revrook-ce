#!/usr/bin/env bash
# Exports the network file revrook reads from one UniFi console (UniFi OS gateway with the
# Network application, zone-based firewall), with read-only requests.
#
#   network-export-unifi.csv   the gateway (firmware release date, management open to the
#                              internet, syslog target), the inbound rules (port forwards
#                              and allow policies from the External zone) and the Wi-Fi
#                              networks (security mode, guest, isolated)
#
# Needs bash, curl and jq, and an API key of the console (Network application: Settings >
# Integrations > Create New API Key). A key has the rights of the admin who creates it;
# the script only sends GET requests and writes the key nowhere. Give it an expiry.
#
#   UNIFI_URL=https://192.168.1.1 UNIFI_API_KEY=... ./export-unifi.sh ./contoso-2026-11
#
# The firmware release date comes from Ubiquiti's public firmware list
# (fw-update.ui.com, no key). Each line names its tool as unifi:<gateway name>, so the
# files of two consoles of one client count together. Served by revrook at
# /static/scripts/export-unifi.sh; guide: docs/guides/12-cloud-exports.md.
set -euo pipefail
# jq on Windows (Git Bash) ends its lines with CRLF: drop the CR so no value carries it.
jq() { command jq "$@" | tr -d '\r'; }

out=${1:?usage: export-unifi.sh OUTPUT_FOLDER   (UNIFI_URL and UNIFI_API_KEY must be set)}
: "${UNIFI_URL:?set UNIFI_URL to the console, e.g. https://192.168.1.1}"
: "${UNIFI_API_KEY:?set UNIFI_API_KEY to an API key of the console}"
mkdir -p "$out"
now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
# shortcut: -k accepts the console's own self-signed certificate; set UNIFI_CA to a CA file to verify it.
get() { curl -fsS ${UNIFI_CA:+--cacert "$UNIFI_CA"} ${UNIFI_CA:-"-k"} -H "X-API-KEY: $UNIFI_API_KEY" "${UNIFI_URL%/}/proxy/network/$1"; }

get "integration/v1/sites" >"$work/sites.json"
site=$(jq -r --arg name "${UNIFI_SITE:-}" \
  '.data | (map(select(.name == $name or .internalReference == $name)) + .)[0].id' "$work/sites.json")
ref=$(jq -r --arg id "$site" '.data[] | select(.id == $id) | .internalReference // "default"' "$work/sites.json")
all() { # every page of an Integration API list, as one array
  local offset=0 total=1; : >"$work/page"
  while [ "$offset" -lt "$total" ]; do
    get "integration/v1/sites/$site/$1?limit=200&offset=$offset" >"$work/one"
    jq -c '.data[]' "$work/one" >>"$work/page"
    total=$(jq '.totalCount' "$work/one"); offset=$((offset + 200))
  done
  jq -s . "$work/page"
}
all firewall/zones >"$work/zones.json"
all firewall/policies >"$work/policies.json"
all traffic-matching-lists >"$work/lists.json"
all wifi/broadcasts >"$work/wifi.json"
get "api/s/$ref/stat/device" >"$work/devices.json"
get "api/s/$ref/rest/portforward" >"$work/forwards.json"
get "api/s/$ref/rest/setting" >"$work/settings.json"

model=$(jq -r '[.data[] | select(.type == "udm" or .type == "ugw" or .type == "uxg")][0].model // ""' "$work/devices.json")
version=$(jq -r '[.data[] | select(.type == "udm" or .type == "ugw" or .type == "uxg")][0].version // ""' "$work/devices.json")
released=""
if [ -n "$model" ] && [ -n "$version" ]; then
  # Versions read 5.1.34.34103 on the console and v5.1.34+2e23191 in the list.
  released=$(curl -fsS "https://fw-update.ui.com/api/firmware?filter=eq~~platform~~$model&limit=200" |
    jq -r --arg v "v$(echo "$version" | cut -d. -f1-3)" \
      '[._embedded.firmware[] | select(.version | split("+")[0] == $v) | .created][0] // "" | .[0:10]') || released=""
fi

jq -r --arg now "$now" --arg released "$released" \
  --slurpfile zones "$work/zones.json" --slurpfile policies "$work/policies.json" \
  --slurpfile lists "$work/lists.json" --slurpfile wifi "$work/wifi.json" \
  --slurpfile forwards "$work/forwards.json" --slurpfile settings "$work/settings.json" '
  def csv: map(tostring | if test("[\",]") then "\"" + gsub("\""; "\"\"") + "\"" else . end) | join(",");
  ($zones[0] | map({key: .id, value: .name}) | from_entries) as $zone
  | ($lists[0] | map({key: .id, value: .items}) | from_entries) as $list
  | (.data | map(select(.type == "udm" or .type == "ugw" or .type == "uxg"))[0]) as $gw
  | "unifi:" + ($gw.name // "gateway") as $tool
  | ($settings[0].data | map({key: .key, value: .}) | from_entries) as $set
  | def ports($filter):
      if $filter == null then ["any"]
      elif $filter.type == "TRAFFIC_MATCHING_LIST" then ($list[$filter.trafficMatchingListId] // []) | map(.value // "\(.start)-\(.stop)" | tostring)
      else ($filter.items // []) | map(if .type == "PORT_RANGE" then "\(.start)-\(.stop)" else (.value | tostring) end)
      end;
    def sources($filter):
      if ($filter.type // "") == "IP_ADDRESS" then ($filter.ipAddressFilter.items // []) | map(.value // "\(.start)-\(.stop)") | join(" ") else "any" end;
    # Allow policies from the internet that start connections (return traffic does not;
    # port forwards are read from the forwards themselves, with their internet port).
    [ $policies[0][] | select(.enabled and .action.type == "ALLOW" and $zone[.source.zoneId] == "External"
        and (.name | test("Return Traffic|^Allow Port Forward") | not)) ] as $inbound
  | ([ $inbound[] | select($zone[.destination.zoneId] == "Gateway"
        and ((.ipProtocolScope.protocolFilter.protocol.name // "TCP") | test("TCP|ALL"))
        and (ports(.destination.trafficFilter.portFilter // null) | any(. == "any" or . == "22" or . == "80" or . == "443" or . == "8443"))) ]
      | length > 0) as $wan_admin
  | ["record_type","device_id","perimeter","firmware_release_date","wan_admin_enabled","default_credentials_flag","syslog_target","rule_enabled","direction","action","source","destination_port","ssid","security_mode","guest_ssid","guest_isolated","tool","exported_at"],
    # A UniFi OS console has an owner account from its setup: there is no default login.
    ["device", ($gw.name // "gateway"), "true", $released, ($wan_admin | tostring), "false",
     (if ($set.rsyslogd.enabled // false) and ($set.rsyslogd.this_controller // false | not) then ($set.rsyslogd.ip // "") else "" end),
     "","","","","","","","","",$tool,$now],
    ( $forwards[0].data[] | select(.enabled != false) | . as $f
      | (.dst_port | tostring | split(",")[])
      | ["rule", $f.name, "", "", "", "", "", "true", "inbound", "allow",
         (if ($f.src // "any") == "any" or ($f.src // "") == "" then "any" else $f.src end), ., "", "", "", "", $tool, $now] ),
    # ICMP opens no port, so it is left out (a line without a port reads as undecided).
    ( $inbound[] | select((.ipProtocolScope.protocolFilter.protocol.name // "") | test("ICMP") | not) | . as $p
      | ports(.destination.trafficFilter.portFilter // null)[]
      | ["rule", $p.name, "", "", "", "", "", "true", "inbound", "allow",
         sources($p.source.trafficFilter // null), ., "", "", "", "", $tool, $now] ),
    ( $wifi[0][] | . as $w
      | ([$zones[0][] | select(.networkIds | index($w.network.networkId // "")) | .name][0] // "") as $wzone
      | ($wzone | test("^(Guest|Hotspot)$")) as $guest
      | ($zones[0] | map(select(.name == $wzone) | .id)) as $own
      | ([ $policies[0][] | select(.enabled and .action.type == "ALLOW" and (.metadata.origin // "") == "USER_DEFINED"
            and (.source.zoneId | IN($own[])) and ($zone[.destination.zoneId] | IN("External", "Gateway", $wzone) | not)) ] | length == 0) as $isolated
      | ["ssid", "", "", "", "", "", "", "", "", "", "", "", $w.name,
         ({"OPEN":"open","WPA2_PERSONAL":"wpa2","WPA2_WPA3_PERSONAL":"wpa2-wpa3","WPA3_PERSONAL":"wpa3","WPA2_ENTERPRISE":"wpa2-enterprise","WPA3_ENTERPRISE":"wpa3-enterprise","WPA2_WPA3_ENTERPRISE":"wpa2-enterprise"}[$w.securityConfiguration.type // ""] // ($w.securityConfiguration.type // "" | ascii_downcase)),
         ($guest | tostring), (if $guest then ($isolated | tostring) else "" end), $tool, $now] )
  | csv' "$work/devices.json" >"$out/network-export-unifi.csv"

echo "network-export-unifi.csv: $(($(wc -l <"$out/network-export-unifi.csv") - 1)) rows"
echo Done
