# Importers (phases 3 and 4)

An importer turns one export into facts: counts and flags. It never stores a
personal identifier. It names the identifier (a user, a device) and the evidence
store replaces it with the client's pseudonym before anything is written
(`app/importers/base.py`, `app/evidence/service.py`). The security rules are in
`docs/security.md`.

Source codes: `entra-registration`, `secure-score`, `intune-devices`,
`conditional-access`, `directory-roles` (phase 3), `reference-csv` (phase 2, used
to prove the pipeline) and, from phase 4, `device-inventory`, `backup-export`,
`network-export`, `training-csv`, `leavers-csv` and `exchange-export`.

## How a file is read

1. The bytes become text: UTF-8 with or without a byte order mark, UTF-16 with a
   mark, anything else through `charset-normalizer`. NUL bytes refuse the file.
2. A file that starts with `{` or `[` is JSON; anything else is CSV. The kind of
   source is never taken from the file name. A CSV is matched to the contract by
   its header: case, spaces and punctuation are ignored, and a `_loc` suffix (a
   localised Intune column) is ignored. The six phase 4 sources are CSV only; a
   JSON file sent to one of them is refused.
3. A required column or field that is missing refuses the file and names it, for
   example `The file is missing the column User principal name.` When exactly one
   other Microsoft source fits the file, the message adds `This looks like ...
   (source ...)`.
4. A row that cannot be read is counted in `rows_rejected`, its reason (the column,
   never the content) is kept as a `<prefix>.reject` fact for the first 50 rows, and
   the rest of the file is still imported. A file in which no row can be read is
   refused.
5. Limits: 20 MB, 200,000 rows, JSON nested at most 12 levels deep, no JSON list
   longer than the row limit, no CSV field above 131,072 characters. The file is
   read in memory, bounded by the 20 MB limit that the evidence store enforces
   before the importer sees it; it is not streamed.

Every file gets one summary fact, `<prefix>.summary`, with its counts and three
flags that are the same for every source:

| Field | Meaning |
| --- | --- |
| `rows_rejected` | Rows that could not be read. |
| `capture_time_source` | `file` when the file or its tool says when it was captured; `upload` when it does not. The evidence store then uses the time given with the upload. |
| `timezone_assumed_utc` | A time in the file had no time zone and was read as UTC. |

The capture time of a file is the top-level `capturedAt` of a JSON object, the
newest `createdDateTime` of Secure Score, or none (CSV exports carry no time).

### Dates without a time zone

A date or time must be ISO 8601 and between the years 2000 and 2100. When it has
no time zone it is read as UTC, stored as UTC, and the summary of the file sets
`timezone_assumed_utc` to `true` so the report can say so. A date such as
`2026-10-01` is read as midnight UTC.

### Text that looks like an email address (carry-over N3)

A short text field (a course name, an antivirus product) that contains something
like an email address is not kept: the row is rejected with `<column> must not
contain an email address`, and the rest of the file is imported. Before phase 4 the
evidence store refused the whole upload for it. Identifier columns (the user, the
device, the mailbox, the domain) are not text fields: they are replaced by
pseudonyms and may contain an at sign.

## Saved column mappings

A vendor file with other column names can be read through a mapping: a vendor
header, exactly as written, to the name of a column of the source (the `key` in
the tables below). `POST /api/v1/clients/{id}/import-profiles` saves one
(`name`, `source_code`, `mapping`) for a client; an upload names it with the form
field `profile_id`. A mapping wins over name matching, applies to CSV only, and
belongs to one client and one source (`app/importers/profiles.py`). It works for
all eleven CSV sources, the six of phase 4 included. The editor page with a
preview is part 2 of phase 4 (Frontend); this part provides the API.

## The five Microsoft sources

Fields and columns marked **INFERRED** are not in the phase plan's list for the
source (`phase-plan-3`, phase 3). They follow the Microsoft Graph names or a
sensible convention, and no control depends on them yet. Fixtures use them
because the adapters accept them.

### `entra-registration` (prefix `entra`)

Graph `reports/authenticationMethods/userRegistrationDetails` as JSON, or a CSV.

| Key | CSV column | JSON field | Required |
| --- | --- | --- | --- |
| `upn` | User principal name | `userPrincipalName` | yes |
| `mfa_capable` | MFA Capable | `isMfaCapable` | yes |
| `passwordless_capable` | Passwordless Capable | `isPasswordlessCapable` | CSV yes |
| `methods` | Methods registered | `methodsRegistered` | CSV yes |
| `updated` | Last Updated Time | `lastUpdatedDateTime` | CSV yes |
| `mfa_registered` | MFA Registered (INFERRED) | `isMfaRegistered` | JSON yes |
| `is_admin` | Is Admin (INFERRED) | `isAdmin` | no |
| `user_type` | User type (INFERRED) | `userType` | no |

A JSON file must have `userPrincipalName`, `isMfaRegistered` and `isMfaCapable` in
its first record. Facts: `entra.user` (flags, the number of methods, the update
time; the user is a pseudonym). Summary: `users`, `admins`, `guests`,
`mfa_registered`, `mfa_registered_known` (false for the CSV, which has no such
column: the count is then not a measurement), `mfa_capable`,
`passwordless_capable`, `report_updated_at` (the newest update time).

### `secure-score` (prefix `secure_score`)

Graph `security/secureScores` as JSON, or a CSV with a date and a score column.

| Key | CSV column | JSON field | Required |
| --- | --- | --- | --- |
| `date` | Date (INFERRED; also Created) | `createdDateTime` | yes |
| `score` | Score (INFERRED; also Current score) | `currentScore` | yes |
| `max_score` | Max score (INFERRED) | `maxScore` | JSON yes |

JSON also reads `licensedUserCount`, `activeUserCount` (INFERRED), `enabledServices`
(counted) and `controlScores` (`controlName`, `controlCategory`, `score`). Only the
newest reading of the file is kept. Facts: `secure_score.control` (name, category,
score). Summary: `entries`, `current_score`, `max_score`, `licensed_users`,
`active_users`, `services`, `controls`, `score_created_at`. Scores are stored as
exact decimal text (`"48.5"`), never as floating point.

### `intune-devices` (prefix `intune`)

The Intune export job as CSV, or Graph `deviceManagement/managedDevices` as JSON.

| Key | CSV column | JSON field | Required |
| --- | --- | --- | --- |
| `device_id` | DeviceId | `id` | yes |
| `compliance` | ComplianceState | `complianceState` | yes |
| `os` | OS | `operatingSystem` | yes |
| `last_contact` | LastContact | `lastSyncDateTime` | yes |
| `management` | ManagementAgent | `managementAgent` | no |
| `owner` | OwnerType | `ownerType` | no |
| `os_version` | OSVersion | `osVersion` | no |
| `upn` | UPN | `userPrincipalName` | no |
| `encrypted` | IsEncrypted (INFERRED; also Encrypted) | `isEncrypted` | no |

`DeviceName`, serial numbers, `imei`, `phoneNumber` and `activationLockBypassCode`
are never read; the summary says `sensitive_fields_dropped` when the file had one.
The device id and the user are identifiers (pseudonyms). Facts: `intune.device`
(compliance state from a fixed list, operating system family, version, management
agent, owner type, encryption flag, last contact). Summary: `devices`, `compliant`,
`noncompliant`, `windows`, `macos`, `ios`, `android`, `personal`, `with_user`,
`encryption_known`, `encrypted`, `sensitive_fields_dropped`. A file whose times lack
a zone sets `timezone_assumed_utc`.

### `conditional-access` (prefix `ca`)

Graph `identity/conditionalAccess/policies`, JSON only. Each policy needs `state`
and `conditions`. Policy names are never read. Facts: `ca.policy` (state, whether it
covers all users and all applications, whether it requires MFA or blocks, whether it
targets roles, the number of exclusions, whether it covers legacy clients, the
modified time). Summary: `policies`, `enabled`, `report_only`, `disabled`,
`tenant_state`. An empty list is not a failure: `tenant_state` is
`security-defaults`.

### `directory-roles` (prefix `roles`)

Graph `directoryRoles?$expand=members` as JSON, or a manual administrator list as
CSV.

| Key | CSV column | JSON field | Required |
| --- | --- | --- | --- |
| `upn` | User principal name | `members[].userPrincipalName` | yes |
| `role` | Role (INFERRED; also Role name) | `displayName` | yes |
| `enabled` | Enabled (INFERRED) | `members[].accountEnabled` | no |
| `permanent` | Permanent (INFERRED) | none | no |

A JSON file must have `displayName` and `members`. A member that is not a user (a
service principal) is counted in `non_user_members`. Facts: `roles.assignment`
(role, whether it is Global Administrator, the two flags; the user is a pseudonym).
Summary: `assignments`, `roles`, `users`, `global_admins` (people, not
assignments), `non_user_members`, `input_format` (`graph-json` or `manual-csv`).

## The six generic and administrative sources (phase 4)

These are contracts of our own for exports that no vendor shares a format for: an
MSP maps the export of its RMM, backup or network product onto them with a saved
column mapping. They are CSV only. A column is matched by its key, its label or an
alias (case, spaces and punctuation ignored). "Header" below means the column must
be in the file; "row" means an empty cell rejects that row. A column that is
optional and absent gives an unknown value (`null`), and the summary counts how many
values are known (`*_known`), so a missing column is never read as `false`.

A CSV carries no capture time, so for all six `capture_time_source` is `upload`.
Personal identifiers (a user, a device, a mailbox, a mail domain, a network name)
are named as identifiers and become pseudonyms; serial numbers and client names are
never read, and the summary says `unread_columns_present` when the file had such a
column. Words from a fixed list are stored as one of the listed words (`other`
for any other word); free text is cut to 100 characters, never starts like a
spreadsheet formula, and a text that looks like an email address rejects the row.
Counts accept at most 18 digits.

The columns marked **INFERRED** have no counterpart in `rnd-report-3` section 3.4:
they are our choice of name or accepted word list, and no control depends on them.

### `device-inventory` (prefix `inventory`)

One row per device, with patch and antivirus state. Either `device_id` or
`hostname` must be a column; a row needs one of them, plus `os` and `last_seen`.

| Key | Label (aliases) | Header | Reads |
| --- | --- | --- | --- |
| `device_id` | device_id (Device Id, Asset id) | one of two | identifier |
| `hostname` | hostname (Computer name, Device name) | one of two | identifier |
| `os` | os | yes | family: windows, macos, ios, android, linux, other |
| `form_factor` | form_factor (INFERRED) | no | server, workstation, mobile (desktop and laptop are workstation) |
| `os_build` | os_build | no | a version such as 10.0.22631 |
| `last_seen` | last_seen (last_seen_utc) | yes | time |
| `patch_status` | patch_status | yes | up_to_date, pending, unknown |
| `pending_critical_updates` | pending_critical_updates (pending_critical) | yes | whole number |
| `last_patch` | last_patch (last_patch_utc) | no | time |
| `av_product` | av_product | yes | short text |
| `av_status` | av_status | yes | protected, disabled, unknown |
| `av_signature_date` | av_signature_date (av_def_date_utc) | yes | time |
| `disk_encrypted` | disk_encrypted | yes | true or false |
| `local_admin_count` | local_admin_count | no | whole number |
| `tamper_protection` | tamper_protection | no | true or false |
| `dns_filter_active` | dns_filter_active | no | true or false |
| `log_forwarding` | log_forwarding | no | true or false |
| `user` | user (UPN, user_principal_name) | no | identifier |

Facts: `inventory.device`. Summary: `devices`, the operating system counts
(`windows`, `macos`, `ios`, `android`, `linux`), `servers`, `patch_up_to_date`,
`patch_pending`, `with_pending_critical`, `pending_critical_known`,
`last_patch_known`, `av_protected`, `av_disabled`, `encrypted`, `encryption_known`,
`local_admin_known`, `tamper_protected`, `tamper_known`, `dns_filtered`,
`dns_filter_known`, `log_forwarded`, `log_forwarding_known`, `with_user`,
`last_seen_newest`, `unread_columns_present`.

### `backup-export` (prefix `backup`)

One row per backup job. The system (a device or asset) and the job are identifiers
and are counted, never stored by name. A row needs `system_or_device`.

| Key | Label (aliases) | Header | Reads |
| --- | --- | --- | --- |
| `system_or_device` | system_or_device (asset_id, System, Device) | yes | identifier |
| `backup_job` | backup_job (job_name, Job) | yes | identifier |
| `last_success` | last_success (last_success_utc) | yes | time |
| `last_result` | last_result (last_status, Result) | yes | success, warning, failed |
| `retention_days` | retention_days | yes | whole number |
| `restore_test_date` | restore_test_date (last_restore_test_utc) | yes | time |
| `asset_type` | asset_type (INFERRED) | no | server, workstation, database, exchange, onedrive, sharepoint, teams |
| `schedule_hours` | schedule_hours | no | whole number |
| `encrypted` | encrypted | no | true or false |
| `immutable` | immutable | no | true or false |
| `offsite` | offsite | no | true or false |
| `restore_test_result` | restore_test_result | no | success or failed (pass, fail) |

Facts: `backup.job`. Summary: `jobs`, `success`, `warning`, `failed`,
`schedule_known`, `retention_known`, `encrypted`, `encryption_known`, `immutable`,
`immutable_known`, `offsite`, `offsite_known`, `restore_tested`, `restore_passed`,
`restore_failed`, the counts by asset type (`exchange`, `onedrive`, `sharepoint`,
`teams`), `assets` (distinct systems, case-insensitive), `last_success_newest`,
`unread_columns_present`.

### `network-export` (prefix `network`)

One file holds three kinds of line, told apart by `record_type` (a required
column; the words `device`, `rule`, `ssid`, with `firewall`, `firewallrule`, `wifi`
and `wireless` accepted; an empty cell means `device`). At least one of `device_id`,
`rule_enabled`, `ssid` must be a column. The network name (SSID) and the device are
identifiers; the syslog target is reduced to whether one is set.

| Key | Label (aliases) | Kind | Reads |
| --- | --- | --- | --- |
| `record_type` | record_type (Type, Record) | header | device, rule or ssid |
| `device_id` | device_id (Device, Hostname) | device, row | identifier |
| `perimeter` | perimeter (is_perimeter) | device | true or false |
| `firmware_release_date` | firmware_release_date (firmware_release_utc) | device | time |
| `end_of_support_date` | end_of_support_date | device | time |
| `wan_admin_enabled` | wan_admin_enabled | device | true or false |
| `default_credentials_flag` | default_credentials_flag | device | true or false |
| `syslog_target` | syslog_target | device | whether it is set |
| `rule_enabled` | rule_enabled (enabled) | rule, row | true or false |
| `direction` | direction | rule, row | inbound or outbound |
| `action` | action | rule, row | allow or deny |
| `source` | source | rule | `any` for the whole internet, else `restricted` |
| `destination_port` | destination_port (port) | rule | a port, a range such as 1024-2048, or `any` |
| `ssid` | ssid | ssid, row | identifier |
| `security_mode` | security_mode | ssid, row | open, wep, wpa, wpa2, wpa2-enterprise, wpa3, wpa3-enterprise, wpa2-wpa3, owe |
| `guest_isolated` | guest_isolated | ssid | true or false |
| `guest_ssid` | guest_ssid | ssid | true or false |

Facts: `network.device`, `network.rule`, `network.ssid`. Summary: `devices`,
`perimeter_devices`, `wan_admin_enabled`, `default_credentials`,
`syslog_configured`, `rules`, `rules_enabled`, `rules_inbound`, `rules_allow`,
`rules_any_source`, `ssids`, `ssids_open`, `ssids_guest`, `ssids_guest_isolated`,
`firmware_newest`, `unread_columns_present`.

### `training-csv` (prefix `training`)

One row per completed course. Header columns `user_id` (User principal name, UPN),
`course` (Course name, Training) and `completed_utc` (completed, Completed on,
Completion date); a row needs the user and the completion time. The course is a
short text. Summary: `completions`, `users` (distinct people), `completed_newest`,
`unread_columns_present`.

### `leavers-csv` (prefix `leavers`)

One row per person who left. Header columns `user_id` (User principal name, UPN)
and `leave_date` (Leaving date, Last working day); optional `account_enabled`
(accountEnabled). A row needs the user and the leaving date. Summary: `leavers`,
`account_state_known`, `still_enabled`, `users` (distinct people), `leave_newest`,
`unread_columns_present`.

### `exchange-export` (prefix `exchange`)

One record type per line, told apart by the required column `record_type` (Type):
`dkim`, `policy`, `mailbox`, `audit`, `alert`. A line with an empty or unknown type
is a row error.

| Key | Label (aliases) | Record | Reads |
| --- | --- | --- | --- |
| `domain` | domain (Domain) | dkim, row | identifier (the mail domain) |
| `enabled` | enabled (Enabled) | dkim, policy, row | true or false |
| `policy_type` | policy_type (Policy) | policy, row | anti-phish, safe-links, safe-attachments, preset, outbound-spam |
| `auto_forwarding_mode` | auto_forwarding_mode | policy | off, on, automatic |
| `mailbox` | mailbox (Mailbox id, Identity) | mailbox, row | identifier |
| `recipient_type` | recipient_type | mailbox, row | user, shared, room, equipment |
| `forwarding_external` | forwarding_external | mailbox | true or false |
| `account_enabled` | account_enabled | mailbox | true or false |
| `unified_audit_log_enabled` | unified_audit_log_enabled | audit, row | true or false |
| `audit_disabled` | audit_disabled | audit | true or false |
| `alert_kind` | alert_kind | alert, row | admin-role, forwarding-rule, risky-sign-in |
| `disabled` | disabled (Disabled) | alert | true or false |
| `recipient_count` | recipient_count | alert | whole number |
| `last_acknowledged` | last_acknowledged | alert | time |

Facts: `exchange.dkim`, `exchange.policy`, `exchange.mailbox`, `exchange.audit`,
`exchange.alert`. Summary: `dkim_domains`, `dkim_enabled`, `policies`,
`anti_phish_enabled`, `safe_links_enabled`, `safe_attachments_enabled`,
`preset_enabled`, `auto_forwarding_off`, `mailboxes`, `shared_mailboxes`,
`shared_mailboxes_enabled`, `forwarding_external`, `audit_records`,
`audit_ingestion_enabled`, `alerts`, `alerts_with_recipient`,
`alert_admin_role_enabled`, `alert_forwarding_rule_enabled`,
`alert_risky_sign_in_enabled`, `alert_acknowledged_newest`,
`unread_columns_present`.

## The fields of the 51 controls (phase 4)

`tests/control_fields.yaml` lists, for each control of ruleset PC-RULES v0.1
(`rnd-report-3` section 3.4), the fields its rule names, and the one adapter and
one column that carries each. `tests/test_control_fields.py` fails when a field has
no column, has a column in more than one adapter, names a column that no longer
exists, or is read by no control. Phase 5 must keep the list equal to
`data/controls.yaml`.

### Fields no CE importer reads

These fields are named by a control and are not carried by any importer. The check
engine gives such a control `unknown` for them, with the reason below, and never a
guess. They are listed so that the gap is explicit and so that the test can tell a
known gap from an orphan.

| Field | Reason | Why |
| --- | --- | --- |
| `G.user.signInActivity` | `licence_or_scope` | Needs Entra ID P1 and a permission outside the verified list. |
| `G.user.accountEnabled` | `licence_or_scope` | Needs a Graph user listing, which is not among the five Microsoft exports. |
| `G.authorizationPolicy.invitations` | `licence_or_scope` | Needs a Graph permission outside the verified list. |
| `G.deviceConfigurationProfile` | `licence_or_scope` | Needs the Intune configuration profile export, outside the Intune export job. |
| `G.windowsProtectionState` | `licence_or_scope` | Needs a Graph permission outside the verified list. |
| `G.signatureUpdateOverdue` | `licence_or_scope` | Derived from the Windows protection state, which is not read. |
| `G.securityAlerts` | `licence_or_scope` | Needs a Defender licence tier and permission. |
| `G.oauth2PermissionGrants` | `licence_or_scope` | Needs a Graph permission outside the verified list. |
| `G.servicePrincipals` | `licence_or_scope` | Needs a Graph permission outside the verified list. |
| `G.licensedMailboxes` | `licence_or_scope` | The licence listing is not among the five Microsoft exports. |
| `R.threats` | `licence_or_scope` | Depends on the antivirus product; not part of the common device contract. |
| `R.installed_software` | `shipped_list` | Compared with a table we ship and version; no importer carries it. |
| `D.spf` | `dnscheck` | Comes from the public DNS check of phase 7, not from a file. |
| `D.dkim_selectors` | `dnscheck` | Comes from the public DNS check of phase 7, not from a file. |
| `D.dmarc` | `dnscheck` | Comes from the public DNS check of phase 7, not from a file. |

A field of the table above that a later phase adds an importer for moves into the
`fields` section of `tests/control_fields.yaml` in the same change.

## Synthetic fixtures

`python3 tools/make_fixtures.py OUTPUT_DIR [--seed N]` writes the five Microsoft
files the end-to-end script imports, and `manifest.json` with the source code, the
number of facts and the expected summary of each. Everything is invented (the mail
domain is `fixture.example.invalid`), the same seed gives the same bytes, and only
the standard library is used. `variant_fixtures()` adds the other shapes (the Entra
CSV, Intune JSON, an empty policy list, the administrator CSV) for the tests.

`tools/make_generic_fixtures.py` does the same for the six sources of phase 4:
deterministic and seeded, synthetic only, with a manifest of the expected counts and
of the values that must never be read (serial numbers, client names, vendor
placeholders). `scripts/e2e/phase_04.sh`, called by `tests/e2e/run.sh`, imports
them through the running stack and checks the counts, a saved mapping, a missing
column, hostile files, that no unread value is in the database dump, and the delete
of a client.
