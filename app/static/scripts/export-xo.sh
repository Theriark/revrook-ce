#!/usr/bin/env bash
# Exports the backup file revrook reads from Xen Orchestra (REST API /rest/v0), with
# read-only requests.
#
#   backup-export-xo.csv   one line per VM of each backup job (one per metadata job): the
#                          job's newest result and newest success, how often it runs and
#                          how long it keeps backups, and whether its repositories are
#                          encrypted and away from the site
#
# Needs bash, curl and jq, and an authentication token of an XO user that can read the
# backup jobs, schedules, logs, repositories and VMs (user menu > Authentication tokens >
# New token; give it an expiry). The script only sends GET requests and writes the token
# nowhere; repository addresses (which may hold keys) are never written.
#
#   XO_URL=https://xo.example XO_TOKEN=... ./export-xo.sh ./contoso-2026-11
#
# XO_NAME_SEPARATOR cuts VM names at a separator ("VM-05 | AI" with " | " gives VM-05), so
# they match the host names of the device inventory (PC-BCK-01 joins them). A repository is
# encrypted when its address carries an encryption key, and away from the site when it is
# object storage (s3, azure); a file share on a private address is on site. Restore tests
# (health checks) and immutability are not read, so revrook shows them unknown. Served by
# revrook at /static/scripts/export-xo.sh; guide: docs/guides/12-cloud-exports.md.
set -euo pipefail
# jq on Windows (Git Bash) ends its lines with CRLF: drop the CR so no value carries it.
jq() { command jq "$@" | tr -d '\r'; }

out=${1:?usage: export-xo.sh OUTPUT_FOLDER   (XO_URL and XO_TOKEN must be set)}
: "${XO_URL:?set XO_URL to Xen Orchestra, e.g. https://xo.example}"
: "${XO_TOKEN:?set XO_TOKEN to an XO authentication token}"
mkdir -p "$out"
now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
# shortcut: -k accepts a self-signed XO certificate; set XO_CA to a CA file to verify it.
get() { curl -fsS ${XO_CA:+--cacert "$XO_CA"} ${XO_CA:-"-k"} -b "authenticationToken=$XO_TOKEN" "${XO_URL%/}/rest/v0/$1"; }
get "backup-jobs?fields=id,name,type,mode,remotes,settings,vms" >"$work/jobs.json"
get "schedules?fields=id,jobId,cron,enabled" >"$work/schedules.json"
get "backup-logs?fields=jobId,status,start,end" >"$work/logs.json"
get "backup-repositories?fields=id,url" >"$work/repos.json"
get "vms?fields=id,name_label,tags" >"$work/vms.json"

jq -r --arg now "$now" --arg sep "${XO_NAME_SEPARATOR:-}" \
  --slurpfile schedules "$work/schedules.json" --slurpfile logs "$work/logs.json" \
  --slurpfile repos "$work/repos.json" --slurpfile vms "$work/vms.json" '
  def csv: map(tostring | if test("[\",]") then "\"" + gsub("\""; "\"\"") + "\"" else . end) | join(",");
  def iso: if . == null then "" else (. / 1000 | floor | todate) end;
  def ids: if type == "string" then [.] elif type == "object" then (.__or // []) else [] end;
  # Hours between two runs of a cron schedule (minute hour day month weekday).
  def hours: split(" ") as $c
    | if ($c[3] | test("^\\*/")) then 24 * 30 * ($c[3][2:] | tonumber)
      elif $c[2] != "*" then 24 * 30
      elif $c[4] != "*" then (168 / ($c[4] | split(",") | length))
      else (24 / ($c[1] | split(",") | length)) end | floor;
  # The VMs a job backs up: by id, or by tags (any tag of the first rule, none of __not).
  def members($pattern):
    if $pattern == null then []
    elif $pattern.id != null then ($pattern.id | ids) as $want | [$vms[0][] | select(.id | IN($want[]))]
    else ([$pattern.tags.__and[]? | .__or? // empty | .[] | .[]] + [$pattern.tags.__or[]? | .[]]) as $with
      | ([$pattern.tags.__and[]? | .__not.__or? // empty | .[] | .[]]) as $without
      | [$vms[0][] | select(any(.tags[]; IN($with[])) and (any(.tags[]; IN($without[])) | not))]
    end;
  def name: if $sep != "" then split($sep)[0] else . end;
  ["system_or_device","backup_job","last_success","last_result","retention_days","restore_test_date","asset_type","schedule_hours","encrypted","immutable","offsite","tool","exported_at"],
  ( .[] | . as $job
    | [$schedules[0][] | select(.jobId == $job.id and .enabled)] as $on
    | select($on | length > 0)
    | ([$on[] | .cron | hours] | min) as $every
    | ([$on[] | (($job.settings[.id].exportRetention // $job.settings[.id].copyRetention // 0) * (.cron | hours) / 24)] | max | ceil) as $keep
    | ([$logs[0][] | select(.jobId == $job.id and .status != "pending")] | sort_by(.start) | reverse) as $runs
    | ($runs[0].status // null) as $last
    | ([$runs[] | select(.status == "success")][0].end) as $ok
    | (($job.remotes.id // null) | ids) as $rids
    | [$repos[0][] | select(.id | IN($rids[]))] as $where
    | [ ($where | length > 0 and all(.url | test("encryptionKey")) | tostring),
        (if ($where | length) == 0 then "" elif any($where[]; .url | test("^(s3|azure)")) then "true"
         elif all($where[]; .url | test("//([^@/]*@)?(10\\.|192\\.168\\.|172\\.(1[6-9]|2[0-9]|3[01])\\.)")) then "false" else "" end) ] as $repo
    | (if $job.type == "metadataBackup" then [{name_label: $job.name}] else members($job.vms) end)[]
    | [ (.name_label | name), $job.name, ($ok | iso),
        (if $last == null then "" elif $last == "success" then "success" elif $last == "skipped" then "warning" else "failed" end),
        (if $keep > 0 then $keep else "" end), "", (if $job.type == "metadataBackup" then "" else "server" end), $every,
        $repo[0], "", $repo[1], "xo", $now ] )
  | csv' "$work/jobs.json" >"$out/backup-export-xo.csv"

echo "backup-export-xo.csv: $(($(wc -l <"$out/backup-export-xo.csv") - 1)) rows"
echo Done
