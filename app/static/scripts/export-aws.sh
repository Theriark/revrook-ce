#!/usr/bin/env bash
# Exports the AWS files revrook reads, for one AWS account, with read-only calls.
#
#   network-export-aws.csv     inbound security group rules of every enabled region
#   device-inventory-aws.csv   running EC2 instances (written only when there are any)
#   backup-export-aws.csv      AWS Backup jobs by resource (written only when there are any)
#
# Drop the folder on Import evidence in revrook: each file is recognised by its columns.
# CSV files carry no capture time, so set "exported at" on the import page.
#
# Needs bash, awk and AWS CLI v2, signed in to the client's account. The calls are
# describe/list only (the AWS managed policy ReadOnlyAccess or SecurityAudit is enough):
#
#   aws sso login --profile contoso
#   AWS_PROFILE=contoso ./export-aws.sh ./contoso-aws-2026-11
#
# Nothing in the account is changed and no credential is written. Served by revrook at
# /static/scripts/export-aws.sh; guide: docs/guides/12-cloud-exports.md.
set -euo pipefail

out=${1:?usage: export-aws.sh OUTPUT_FOLDER   (AWS_PROFILE picks the account)}
mkdir -p "$out"
now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
aws sts get-caller-identity --query Account --output text >/dev/null # fail early when not signed in
regions=$(aws ec2 describe-regions --query 'Regions[].RegionName' --output text | tr -d '\r')

# Text output of the AWS CLI: tab-separated, "None" for an empty value, CRLF on Windows.
csv='function q(v) { if (v == "None") v = ""; gsub(/"/, "\"\"", v); return (v ~ /[",]/) ? "\"" v "\"" : v }
     { sub(/\r$/, "") }'

net="$out/network-export-aws.csv"
echo "record_type,device_id,rule_enabled,direction,action,source,destination_port,tool" >"$net"
dev=$(mktemp); vol=$(mktemp); map=$(mktemp); bak=$(mktemp)
trap 'rm -f "$dev" "$vol" "$map" "$bak"' EXIT
for r in $regions; do
  # A rule that admits a security group of the same VPC can only be reached from that
  # VPC, so its source is the VPC's address blocks. A group across a peering and a prefix
  # list stay empty (unknown), so revrook never counts them as restricted.
  aws ec2 describe-vpcs --region "$r" --output text \
    --query 'Vpcs[].[VpcId,join(`" "`,[CidrBlockAssociationSet[].CidrBlock,(Ipv6CidrBlockAssociationSet || `[]`)[].Ipv6CidrBlock][])]' >"$map"
  aws ec2 describe-security-groups --region "$r" --output text \
    --query 'SecurityGroups[].[GroupId,VpcId]' >>"$map"
  aws ec2 describe-security-group-rules --region "$r" --output text \
    --query 'SecurityGroupRules[?IsEgress==`false`].[GroupId,IpProtocol,FromPort,ToPort,CidrIpv4,CidrIpv6,ReferencedGroupInfo.GroupId,ReferencedGroupInfo.VpcPeeringConnectionId]' |
    awk -F'\t' -v r="$r" -v map="$map" "$csv"'
      FILENAME == map { if ($1 ~ /^vpc-/) cidr[$1] = $2; else vpc[$1] = $2; next }
      NF >= 8 {
        port = ($2 == "-1" || $3 == "-1") ? "any" : ($3 == $4 ? $3 : $3 "-" $4)
        if ($2 ~ /^(icmp|icmpv6|1|58)$/) port = "" # ICMP has a type and code, not ports
        src = ($5 != "None") ? $5 : $6
        if ($7 != "None" && $8 == "None") src = cidr[vpc[$1]]
        print "rule," q(r "/" $1) ",true,inbound,allow," q(src) "," port ",aws"
      }' "$map" - >>"$net"

  # shortcut: patch and antivirus state are left unknown (SSM is not read), add SSM patch states when a client runs SSM.
  aws ec2 describe-volumes --region "$r" --query 'Volumes[].[Attachments[0].InstanceId,Encrypted]' \
    --output text >"$vol"
  aws ec2 describe-instances --region "$r" --filters Name=instance-state-name,Values=running \
    --query 'Reservations[].Instances[].[InstanceId,PlatformDetails]' --output text |
    awk -F'\t' -v now="$now" -v vol="$vol" "$csv"'
      FILENAME == vol { if ($1 != "None") enc[$1] = (enc[$1] == "false") ? "false" : tolower($2); next }
      NF >= 2 {
        os = tolower($2) ~ /windows/ ? "windows" : "linux"
        print q($1) "," os ",server," now ",unknown,,,unknown,," (($1 in enc) ? enc[$1] : "") ",aws"
      }' "$vol" - >>"$dev"
done

if [ -s "$dev" ]; then
  { echo "hostname,os,form_factor,last_seen,patch_status,pending_critical_updates,av_product,av_status,av_signature_date,disk_encrypted,tool"
    cat "$dev"; } >"$out/device-inventory-aws.csv"
else
  echo "No running EC2 instance: device-inventory-aws.csv not written."
fi

for r in $regions; do
  # Newest job first per resource and plan: that is the last result; the newest
  # completed one is the last success.
  aws backup list-backup-jobs --region "$r" \
    --query 'BackupJobs[].[CreationDate,ResourceArn,CreatedBy.BackupPlanId,State,CompletionDate,ResourceType,BackupVaultName]' \
    --output text | tr -d '\r' | sort -r | cut -f2- | awk -F'\t' "$csv"'
      NF >= 6 {
        key = $1 "\t" $2; plan = ($2 == "None") ? "on-demand" : $2
        if ($3 ~ /^(CREATED|PENDING|RUNNING|ABORTING)$/) next
        if (!(key in result)) {
          order[++n] = key; system_[key] = $1; job[key] = plan " (" $6 ")"
          result[key] = $3 == "COMPLETED" ? "success" : ($3 == "PARTIAL" ? "warning" : "failed")
          t = tolower($5); type[key] = t ~ /^(ec2|ebs|efs|fsx|storage gateway)/ ? "server" : (t ~ /rds|aurora|dynamodb|documentdb|neptune|redshift|timestream/ ? "database" : "")
        }
        if ($3 == "COMPLETED" && !(key in ok)) ok[key] = $4
      }
      END { for (i = 1; i <= n; i++) { k = order[i]
        print q(system_[k]) "," q(job[k]) "," q(ok[k]) "," result[k] ",,," type[k] ",,aws" } }' >>"$bak"
done
if [ -s "$bak" ]; then
  # Retention, encryption and restore tests are not in the job list; revrook reads the empty cells as unknown.
  { echo "system_or_device,backup_job,last_success,last_result,retention_days,restore_test_date,asset_type,encrypted,tool"
    cat "$bak"; } >"$out/backup-export-aws.csv"
else
  echo "No AWS Backup job: backup-export-aws.csv not written."
fi

# Every line says when it was exported: revrook reads it as the file's capture time, and an
# export of an unchanged account still differs from the last one, so it is never refused.
stamp() { awk -v t="$now" 'NR == 1 { print $0 ",exported_at"; next } { print $0 "," t }' "$1" >"$1.tmp" && mv "$1.tmp" "$1"; }
stamp "$net"
[ -s "$dev" ] && stamp "$out/device-inventory-aws.csv"
[ -s "$bak" ] && stamp "$out/backup-export-aws.csv"
for f in "$out"/*-aws.csv; do echo "$(basename "$f"): $(($(wc -l <"$f") - 1)) rows"; done
echo Done
