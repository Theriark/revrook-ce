# 12. Export the cloud accounts and the office tools with scripts

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

## Cloudflare: `export-cloudflare.sh`

You need `curl`, `jq` and a Cloudflare API token of the client with two read-only
permissions: **Cloudflare Tunnel Read** and **Access: Apps and Policies Read**
(My Profile, API Tokens, Create Token, Custom token). The script sends GET requests
only and writes the token nowhere:

```bash
CLOUDFLARE_API_TOKEN=... ./export-cloudflare.sh ./contoso-cf-2026-11              # every account of the token
CLOUDFLARE_API_TOKEN=... ./export-cloudflare.sh ./contoso-cf-2026-11 ACCOUNT_ID   # one account
```

Every public hostname of a Cloudflare Tunnel is a path from the internet into the
client's network. The script reads each tunnel's routes and the Access applications:

| File | What it holds |
| --- | --- |
| `network-export-cloudflare.csv` | One `rule` line from `any` source per public hostname that no Access application guards, to the port of its service: `ssh` 22, `rdp` 3389, `smb` 445, `tcp` its own port, and 443 for web services. A published SSH or RDP route without Access is what PC-NET-02 looks for. |

A hostname counts as guarded when an Access application covers it (its own name, or a
wildcard such as `*.example.com` over it; an application on a path such as
`example.com/admin` guards only that path) and the application has at least one policy
and no Bypass policy. Guarded hostnames are counted and not written; the script prints
both numbers. A tunnel configured by a local file (not in the dashboard) has no routes
the API returns; the script names it and skips it. The file is written only when a
hostname is open.

## The office: UniFi, Checkmk and Xen Orchestra

Three more scripts read the tools many MSPs already run on site. They need `bash`,
`curl` and `jq`, and a key of the tool; they send read requests only and write the key
nowhere. A UniFi API key and an XO token have the rights of the account that creates
them, so give them an expiry; the Checkmk user gets the read-only role.

### UniFi: `export-unifi.sh`

An API key of the console (Network application: **Settings > Integrations > Create New
API Key**):

```bash
UNIFI_URL=https://192.168.1.1 UNIFI_API_KEY=... ./export-unifi.sh ./contoso-2026-11
```

| File | What it holds |
| --- | --- |
| `network-export-unifi.csv` | The gateway: its firmware release date (from Ubiquiti's public firmware list), whether a management port (22, 80, 443, 8443) is open from the internet, and its syslog target ("this controller only" is none). One `rule` line per enabled port forward (its internet port and allowed source) and per enabled allow policy from the External zone (return traffic and ICMP, which opens no port, are left out). One `ssid` line per Wi-Fi network: its security mode, guest when its network is in the Guest or Hotspot zone, and isolated unless a policy you made lets that zone reach an internal zone. |

Every line names its tool as `unifi:<gateway name>`, so the files of two consoles of one
client count together. A UniFi OS console has an owner account from its setup, so the
file says it keeps no default login.

### Checkmk: `export-checkmk.sh`

An automation user with the built-in **Guest user** role (**Setup > Users > Add user >
Automation secret for machine accounts**), on Checkmk 2.3 or later:

```bash
CHECKMK_URL=https://monitoring.example/mysite CHECKMK_USER=revrook-export \
CHECKMK_SECRET=... CHECKMK_HOSTS='^(SRV|PC)-' ./export-checkmk.sh ./contoso-2026-11
```

| File | What it holds |
| --- | --- |
| `device-inventory-checkmk.csv` | One line per host with the Checkmk agent (`CHECKMK_HOSTS`, a regular expression on the host name, keeps the client's): its operating system and version from the agent's labels (so PC-DEV-03 can date it), server or workstation, when the agent last answered (the last OK of the `Check_MK` service), and the patch state when an `APT`, `Windows`, `Zypper` or `YUM Updates` service is monitored. Antivirus and disk encryption are not read. |

### Xen Orchestra: `export-xo.sh`

An authentication token (user menu > **Authentication tokens > New token**):

```bash
XO_URL=https://xo.example XO_TOKEN=... XO_NAME_SEPARATOR=' | ' ./export-xo.sh ./contoso-2026-11
```

| File | What it holds |
| --- | --- |
| `backup-export-xo.csv` | One line per VM of each scheduled backup job (by id or by tags) and one per metadata job: the job's newest result and newest success, how often it runs and for how long it keeps backups, whether every repository is encrypted (its address carries an encryption key) and whether it is away from the site (object storage: yes; a share on a private address: no). `XO_NAME_SEPARATOR` cuts VM names (`VM-05 \| AI` gives `VM-05`) so they match the device inventory, which PC-BCK-01 joins. Restore tests and immutability are not read; repository addresses are never written. |

## Import the files

Open **Import evidence**, choose the client and drop the folder (or its files) on the
import area. Each file is recognised by its columns. Every line says when it was
exported (`exported_at`): revrook dates the evidence from it, so the time on the form is
not used, and running a script again next month is imported again even when nothing in
the account changed.

Every line the scripts write names its tool in a `tool` column (`aws`, `gcp`,
`cloudflare`). A client often has several tools for one kind of evidence: the office
firewall and a cloud for the network, or two clouds. For the device, backup and network
sources the checks read the newest file of each tool together, so importing the AWS file
does not push out the firewall's file: it replaces only the previous AWS file. A file
without a `tool` column counts as one more tool, so the firewall export of another
product needs no change. Ages are measured from the newest of these files. A tool's file
stops counting once it is more than 35 days older than the newest file of its kind (the
default maximum age of an export), so a tool the client no longer uses drops out by
itself.
