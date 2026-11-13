#!/usr/bin/env bash
# Exports the device file revrook reads from a Checkmk site (2.3 or later, REST API), with
# read-only requests.
#
#   device-inventory-checkmk.csv   one line per host monitored by the Checkmk agent: its
#                                  operating system and version (the agent's host labels),
#                                  server or workstation, when the agent last answered, and
#                                  the patch state when an update service is monitored
#
# Needs bash, curl and jq, and an automation user of the site with the built-in read-only
# role "Guest user" (Setup > Users > Add user > Automation secret for machine accounts).
#
#   CHECKMK_URL=https://monitoring.example/mysite CHECKMK_USER=revrook-export \
#   CHECKMK_SECRET=... ./export-checkmk.sh ./contoso-2026-11
#
# CHECKMK_HOSTS (a regular expression on the host name) keeps only the client's hosts. A
# host without the agent's operating-system labels (a switch read by SNMP) is not a device
# of this file. Patch state is read from an "APT Updates", "Windows Updates", "Zypper
# Updates" or "YUM Updates" service when one is monitored (OK: up to date; WARN or CRIT:
# pending); antivirus and disk encryption are not read, so revrook shows them unknown.
# Served by revrook at /static/scripts/export-checkmk.sh; guide:
# docs/guides/12-cloud-exports.md.
set -euo pipefail
# jq on Windows (Git Bash) ends its lines with CRLF: drop the CR so no value carries it.
jq() { command jq "$@" | tr -d '\r'; }

out=${1:?usage: export-checkmk.sh OUTPUT_FOLDER   (CHECKMK_URL, CHECKMK_USER, CHECKMK_SECRET)}
: "${CHECKMK_URL:?set CHECKMK_URL to the site, e.g. https://monitoring.example/mysite}"
: "${CHECKMK_USER:?set CHECKMK_USER to the automation user}"
: "${CHECKMK_SECRET:?set CHECKMK_SECRET to its automation secret}"
mkdir -p "$out"
now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
# The list endpoints of Checkmk 2.3+ take their query by POST; nothing is changed.
list() {
  curl -fsS -X POST -H "Authorization: Bearer $CHECKMK_USER $CHECKMK_SECRET" \
    -H "Accept: application/json" -H "Content-Type: application/json" \
    "${CHECKMK_URL%/}/check_mk/api/1.0/domain-types/$1/collections/all" -d "$2"
}
list host '{"columns":["name","labels"]}' >"$work/hosts.json"
list service '{"columns":["host_name","description","state","last_time_ok"],"query":{"op":"or","expr":[
  {"op":"=","left":"description","right":"Check_MK"},
  {"op":"~","left":"description","right":"^(APT|Windows|Zypper|YUM) Updates$"}]}}' >"$work/services.json"

jq -r --arg now "$now" --arg only "${CHECKMK_HOSTS:-}" --slurpfile services "$work/services.json" '
  def csv: map(tostring | if test("[\",]") then "\"" + gsub("\""; "\"\"") + "\"" else . end) | join(",");
  def iso: if . == null or . == 0 then "" else todate end;
  ($services[0].value | map(.extensions)) as $svc
  | ["hostname","os","form_factor","os_build","last_seen","patch_status","pending_critical_updates","av_product","av_status","av_signature_date","disk_encrypted","tool","exported_at"],
    ( .value[] | .extensions | select(.labels["cmk/os_family"] != null)
      | select($only == "" or (.name | test($only)))
      | .name as $host | .labels as $l
      | ([$svc[] | select(.host_name == $host)]) as $mine
      | ([$mine[] | select(.description == "Check_MK")][0].last_time_ok) as $seen
      | ([$mine[] | select(.description | test("Updates$"))][0].state) as $updates
      | [ $host, $l["cmk/os_family"],
          (if ($l["cmk/os_name"] // "") | test("Server") then "server"
           elif $l["cmk/os_family"] == "windows" or $l["cmk/os_family"] == "macos" then "workstation"
           elif $l["cmk/os_family"] == "linux" then "server" else "" end),
          ($l["cmk/os_version"] // ""), ($seen | iso),
          (if $updates == null then "unknown" elif $updates == 0 then "up_to_date" else "pending" end),
          "", "", "unknown", "", "", "checkmk", $now ] )
  | csv' "$work/hosts.json" >"$out/device-inventory-checkmk.csv"

echo "device-inventory-checkmk.csv: $(($(wc -l <"$out/device-inventory-checkmk.csv") - 1)) rows"
echo Done
