#!/usr/bin/env bash
# Exports the Google Cloud files revrook reads, for one client, with read-only calls.
#
#   network-export-gcp.csv     VPC firewall rules (ingress) of every project
#   device-inventory-gcp.csv   running Compute Engine VMs
#   backup-export-gcp.csv      disk snapshots, by disk and snapshot schedule
#
# A file is written only when it has a line. Drop the folder on Import evidence in
# revrook: each file is recognised by its columns. CSV files carry no capture time, so
# set "exported at" on the import page.
#
# Needs bash, awk and the Google Cloud CLI, signed in with an account that can read the
# projects (the role Viewer, or Compute Viewer, is enough):
#
#   gcloud auth login
#   ./export-gcp.sh ./contoso-gcp-2026-11                 # every project you can see
#   ./export-gcp.sh ./contoso-gcp-2026-11 proj-a proj-b   # only these projects
#
# Nothing is changed: a project without the Compute Engine API is skipped, never
# enabled. No credential is written. Served by revrook at /static/scripts/export-gcp.sh;
# guide: docs/guides/12-cloud-exports.md.
set -euo pipefail

out=${1:?usage: export-gcp.sh OUTPUT_FOLDER [PROJECT_ID...]}
shift
mkdir -p "$out"
now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
if [ $# -gt 0 ]; then
  projects="$*"
else
  projects=$(gcloud projects list --format='value(projectId)' | tr -d '\r')
fi

# value() output: tab-separated, CRLF on Windows.
csv='function q(v) { gsub(/"/, "\"\"", v); return (v ~ /[",]/) ? "\"" v "\"" : v }
     { sub(/\r$/, "") }'
net=$(mktemp); dev=$(mktemp); bak=$(mktemp); trap 'rm -f "$net" "$dev" "$bak"' EXIT

for p in $projects; do
  enabled=$(gcloud services list --enabled --project "$p" \
    --filter='config.name=compute.googleapis.com' --format='value(config.name)' | tr -d '\r')
  if [ -z "$enabled" ]; then
    echo "$p: Compute Engine API not enabled, skipped."
    continue
  fi

  # One line per protocol and port of a rule: "tcp:22,tcp:8000-8100,icmp" or "all".
  # A rule with only source tags or service accounts has no address range: its source
  # stays empty (unknown), so revrook never counts it as restricted.
  gcloud compute firewall-rules list --project "$p" --filter='direction=INGRESS' \
    --format="value(name,disabled,sourceRanges.list(separator=' '),allowed[].map().firewall_rule().list(),denied[].map().firewall_rule().list())" |
    awk -F'\t' -v p="$p" "$csv"'
      function emit(spec, action,   n, i, part, proto, port) {
        n = split(spec, part, ",")
        for (i = 1; i <= n; i++) {
          proto = part[i]; port = "any"
          if (index(proto, ":")) { port = substr(proto, index(proto, ":") + 1); proto = substr(proto, 1, index(proto, ":") - 1) }
          if (proto ~ /^(icmp|ipv6-icmp|1|58)$/) port = "" # ICMP has a type, not ports
          print "rule," q(p "/" $1) "," ($2 == "True" ? "false" : "true") ",inbound," action "," q($3) "," port
        }
      }
      NF >= 1 && $1 != "" { if ($4 != "") emit($4, "allow"); if ($5 != "") emit($5, "deny") }' >>"$net"

  # Persistent disks are always encrypted at rest by Google, so disk_encrypted is true.
  # shortcut: patch and antivirus state are left unknown (VM Manager is not read), add OS Config patch reports when a client uses VM Manager.
  gcloud compute instances list --project "$p" --filter='status=RUNNING' \
    --format="value(name,zone.basename(),disks[0].licenses.list())" |
    awk -F'\t' -v p="$p" -v now="$now" "$csv"'
      NF >= 1 && $1 != "" {
        os = tolower($3) ~ /windows/ ? "windows" : "linux"
        print q(p "/" $2 "/" $1) "," os ",server," now ",unknown,,,unknown,,true"
      }' >>"$dev"

  # Newest snapshot first per disk and schedule: its state is the last result; the
  # newest ready one is the last success. Snapshots are encrypted at rest by Google.
  gcloud compute snapshots list --project "$p" --sort-by='~creationTimestamp' \
    --format="value(sourceDisk.basename(),sourceSnapshotSchedulePolicy.basename(),status,creationTimestamp)" |
    awk -F'\t' -v p="$p" "$csv"'
      NF >= 3 && $1 != "" {
        if ($3 ~ /^(CREATING|UPLOADING|DELETING)$/) next
        key = $1 "\t" $2
        if (!(key in result)) {
          order[++n] = key; disk[key] = p "/" $1; job[key] = ($2 == "") ? "manual snapshots" : $2
          result[key] = ($3 == "READY") ? "success" : "failed"
        }
        if ($3 == "READY" && !(key in ok)) ok[key] = $4
      }
      END { for (i = 1; i <= n; i++) { k = order[i]
        print q(disk[k]) "," q(job[k]) "," q(ok[k]) "," result[k] ",,,server,true" } }' >>"$bak"
done

write() { # file, header, lines
  if [ -s "$3" ]; then { echo "$2"; cat "$3"; } >"$out/$1"; echo "$1: $(wc -l <"$3" | tr -d ' ') rows"
  else echo "Nothing found: $1 not written."; fi
}
write network-export-gcp.csv "record_type,device_id,rule_enabled,direction,action,source,destination_port" "$net"
write device-inventory-gcp.csv "hostname,os,form_factor,last_seen,patch_status,pending_critical_updates,av_product,av_status,av_signature_date,disk_encrypted" "$dev"
write backup-export-gcp.csv "system_or_device,backup_job,last_success,last_result,retention_days,restore_test_date,asset_type,encrypted" "$bak"
echo Done
