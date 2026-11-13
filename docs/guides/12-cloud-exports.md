# 12. Export the cloud accounts with scripts

A client's cloud accounts hold the same kind of evidence as its office network: the
firewall rules open to the internet, the servers and their disks, and the backups.
One read-only shell script per cloud writes that evidence in the CSV formats revrook
already reads (`network-export`, `device-inventory` and `backup-export`, see
[importers](../importers.md)), ready to drop on **Import evidence**
([3. Import evidence](03-import-evidence.md)).

Each script runs on your own machine, signed in with your own account in the cloud's
own command-line tool. It only lists and describes; nothing in the account is changed
and no password, key or token is written. The scripts are in `app/static/scripts` in
the repository, and every installation serves them under `/static/scripts/`.

Every script needs `bash` and `awk` (Linux, macOS, or Git Bash and WSL on Windows).

## AWS: `export-aws.sh`

You need AWS CLI v2, signed in to the client's account with a role that can read it
(the AWS managed policy `ReadOnlyAccess` or `SecurityAudit` is enough):

```bash
aws sso login --profile contoso
AWS_PROFILE=contoso ./export-aws.sh ./contoso-aws-2026-11
```

The script reads every region the account has enabled and writes:

| File | What it holds |
| --- | --- |
| `network-export-aws.csv` | One `rule` line per inbound security group rule: its address range as the source (`0.0.0.0/0` and `::/0` are the whole internet) and its port, or `any` for all ports. A rule that admits a security group of the same VPC (the default group admits itself) can only be reached from inside that VPC, so its source is the VPC's address blocks. A rule that admits a group across a VPC peering, or a prefix list, has no address the script reads, so its source is left empty and revrook reads it as unknown, never as restricted. |
| `device-inventory-aws.csv` | One line per running EC2 instance: Windows or Linux, a server, seen at the time of the export, and whether every attached EBS volume is encrypted. Written only when the account runs an instance. |
| `backup-export-aws.csv` | One line per resource and backup plan of AWS Backup: the result of the newest finished job (success, warning for a partial job, failed for a failed, aborted or expired one), the time of the newest successful one, and the asset type (server or database). Written only when the account has backup jobs. |

What the script does not read, so revrook shows it as unknown: the patch and
antivirus state of an instance (Systems Manager is not read), the retention, encryption
and restore tests of a backup, and anything outside EC2 and AWS Backup.

## Google Cloud: `export-gcp.sh`

You need the Google Cloud CLI, signed in with an account that can read the client's
projects (the role Viewer, or Compute Viewer, is enough):

```bash
gcloud auth login
./export-gcp.sh ./contoso-gcp-2026-11                 # every project the account can see
./export-gcp.sh ./contoso-gcp-2026-11 proj-a proj-b   # only these projects
```

A project without the Compute Engine API is skipped (the script says so); the API is
never turned on. For the others it writes:

| File | What it holds |
| --- | --- |
| `network-export-gcp.csv` | One `rule` line per protocol and port of each ingress VPC firewall rule: allow or deny, enabled or disabled, its source ranges, and its port (`any` for all ports). A rule with only source tags or service accounts has no address range, so its source is left empty and revrook reads it as unknown. |
| `device-inventory-gcp.csv` | One line per running VM: Windows when its boot disk carries a Windows licence, otherwise Linux, a server, seen at the time of the export, with an encrypted disk (Google encrypts every persistent disk at rest). |
| `backup-export-gcp.csv` | One line per disk and snapshot schedule (or `manual snapshots`): the state of the newest finished snapshot (ready is success, failed is failed), the time of the newest ready one, encrypted (Google encrypts every snapshot). |

A file with nothing in it is not written. Not read, so shown as unknown: the patch and
antivirus state of a VM (VM Manager is not read), snapshot retention and restore tests,
and Backup and DR Service.

## Import the files

Open **Import evidence**, choose the client and drop the folder (or its files) on the
import area. Each file is recognised by its columns. A CSV file carries no capture time,
so set **exported at** on the form to the time the script ran.
