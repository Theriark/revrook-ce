#!/usr/bin/env bash
# Exports the Cloudflare file revrook reads, for one client, with read-only API calls.
#
#   network-export-cloudflare.csv   the public hostnames of every Cloudflare Tunnel that
#                                   are open to the whole internet (no Access application)
#
# Each public hostname of a tunnel is an inbound path from the internet to the client's
# network. One that an Access application guards (with at least one policy, none of them
# Bypass) is reached only by the people of its policies, so it is counted, not written.
# The others are written as rules from `any` source to the port of their service: ssh 22,
# rdp 3389, smb 445, tcp its own port, and 443 for web services.
#
# Needs bash, curl and jq, and a Cloudflare API token of the client with the read-only
# permissions "Cloudflare Tunnel Read" and "Access: Apps and Policies Read":
#
#   CLOUDFLARE_API_TOKEN=... ./export-cloudflare.sh ./contoso-cf-2026-11            # every account of the token
#   CLOUDFLARE_API_TOKEN=... ./export-cloudflare.sh ./contoso-cf-2026-11 ACCOUNT_ID
#
# Only GET requests are sent; the token is not written anywhere. Served by revrook at
# /static/scripts/export-cloudflare.sh; guide: docs/guides/12-cloud-exports.md.
set -euo pipefail
# jq on Windows (Git Bash) ends its lines with CRLF: drop the CR so no value carries it.
jq() { command jq "$@" | tr -d '\r'; }

out=${1:?usage: export-cloudflare.sh OUTPUT_FOLDER [ACCOUNT_ID...]   (CLOUDFLARE_API_TOKEN must be set)}
shift
: "${CLOUDFLARE_API_TOKEN:?set CLOUDFLARE_API_TOKEN to a read-only Cloudflare API token}"
mkdir -p "$out"
now=$(date -u +%Y-%m-%dT%H:%M:%SZ)

api() { curl -fsS -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" "https://api.cloudflare.com/client/v4/$1"; }
# Every page of a list, as one JSON array.
all() {
  local page=1 pages=1 sep='?'
  case "$1" in *\?*) sep='&' ;; esac
  while [ "$page" -le "$pages" ]; do
    body=$(api "$1${sep}per_page=50&page=$page")
    jq -c '.result' <<<"$body"
    pages=$(jq -r '.result_info.total_pages // 1' <<<"$body")
    page=$((page + 1))
  done | jq -cs 'add // []'
}

if [ $# -gt 0 ]; then accounts="$*"; else accounts=$(all accounts | jq -r '.[].id'); fi

rules=$(mktemp); trap 'rm -f "$rules"' EXIT
for a in $accounts; do
  apps=$(all "accounts/$a/access/apps")
  while IFS=$'\t' read -r id name; do
    [ -n "$id" ] || continue
    config=$(api "accounts/$a/cfd_tunnel/$id/configurations")
    if [ "$(jq '.result.config.ingress // [] | length' <<<"$config")" = 0 ]; then
      echo "Tunnel $name: no remote configuration (a local config file is not read), skipped."
      continue
    fi
    jq -r --arg t "$name" --argjson apps "$apps" '
      # An application guards a host when its domain (without a path) is the host or a
      # wildcard over it, and it has a policy and no Bypass policy.
      def covers($h): . as $d | ($d | contains("/") | not)
        and ($d == $h or (($d | startswith("*.")) and ($h | endswith($d[1:]))));
      def guarded($h): any($apps[];
        ((.policies // []) | length > 0) and all((.policies // [])[]; .decision != "bypass")
        and any(([.domain] + (.self_hosted_domains // []))[] | select(. != null); covers($h)));
      def port: (capture("^(?<s>[a-z_]+)://[^:/]*(:(?<p>[0-9]+))?") // {s: ""})
        | if .s == "ssh" then "22" elif .s == "rdp" then "3389" elif .s == "smb" then "445"
          elif .s == "tcp" then (.p // "any") else "443" end;
      .result.config.ingress[] | select(.hostname)
      | [(if guarded(.hostname) then "guarded" else "open" end), $t + "/" + .hostname, (.service | port)]
      | @tsv' <<<"$config" >>"$rules"
  done < <(all "accounts/$a/cfd_tunnel?is_deleted=false" | jq -r '.[] | [.id, .name] | @tsv')
done

guarded=$(awk -F'\t' '$1 == "guarded"' "$rules" | wc -l | tr -d ' ')
open=$(awk -F'\t' '$1 == "open"' "$rules" | wc -l | tr -d ' ')
echo "Public hostnames: $open open to the internet, $guarded behind Cloudflare Access (not written)."
if [ "$open" -gt 0 ]; then
  # exported_at: revrook reads it as the capture time (and a repeat export is never a duplicate).
  { echo "record_type,device_id,rule_enabled,direction,action,source,destination_port,tool,exported_at"
    awk -F'\t' -v t="$now" '$1 == "open" { d = $2; gsub(/"/, "\"\"", d); if (d ~ /[",]/) d = "\"" d "\""
      print "rule," d ",true,inbound,allow,any," $3 ",cloudflare," t }' "$rules"; } >"$out/network-export-cloudflare.csv"
  echo "network-export-cloudflare.csv: $open rows"
fi
echo Done
