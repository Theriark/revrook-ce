# Importers (phase 3)

An importer turns one export into facts: counts and flags. It never stores a
personal identifier. It names the identifier (a user, a device) and the evidence
store replaces it with the client's pseudonym before anything is written
(`app/importers/base.py`, `app/evidence/service.py`). The security rules are in
`docs/security.md`.

Source codes: `entra-registration`, `secure-score`, `intune-devices`,
`conditional-access`, `directory-roles` (phase 3) and `reference-csv` (phase 2,
used to prove the pipeline). Phase 4 adds the generic and administrative ones.

## How a file is read

1. The bytes become text: UTF-8 with or without a byte order mark, UTF-16 with a
   mark, anything else through `charset-normalizer`. NUL bytes refuse the file.
2. A file that starts with `{` or `[` is JSON; anything else is CSV. The kind of
   source is never taken from the file name. A CSV is matched to the contract by
   its header: case, spaces and punctuation are ignored, and a `_loc` suffix (a
   localised Intune column) is ignored.
3. A required column or field that is missing refuses the file and names it, for
   example `The file is missing the column User principal name.` When exactly one
   other source fits the file, the message adds `This looks like ... (source ...)`.
4. A row that cannot be read is counted in `rows_rejected`, its reason (the column,
   never the content) is kept as a `<prefix>.reject` fact for the first 50 rows, and
   the rest of the file is still imported. A file in which no row can be read is
   refused.
5. Limits: 20 MB, 200,000 rows, JSON nested at most 12 levels deep, no JSON list
   longer than the row limit, no CSV field above 131,072 characters.

Every file gets one summary fact, `<prefix>.summary`, with its counts and three
flags that are the same for every source:

| Field | Meaning |
| --- | --- |
| `rows_rejected` | Rows that could not be read. |
| `capture_time_source` | `file` when the file or its tool says when it was captured; `upload` when it does not. The evidence store then uses the time given with the upload. |
| `timezone_assumed_utc` | A time in the file had no time zone and was read as UTC. |

The capture time of a file is the top-level `capturedAt` of a JSON object, the
newest `createdDateTime` of Secure Score, or none (CSV exports carry no time).

## Saved column mappings

A vendor file with other column names can be read through a mapping: a vendor
header, exactly as written, to the name of a column of the source (the `key` in
the tables below). `POST /api/v1/clients/{id}/import-profiles` saves one
(`name`, `source_code`, `mapping`) for a client; an upload names it with the form
field `profile_id`. A mapping wins over name matching, applies to CSV only, and
belongs to one client and one source (`app/importers/profiles.py`). The editor with
a preview arrives in phase 4.

## The five sources

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

## Synthetic fixtures

`python3 tools/make_fixtures.py OUTPUT_DIR [--seed N]` writes the five files the
end-to-end script imports, and `manifest.json` with the source code, the number of
facts and the expected summary of each. Everything is invented (the mail domain is
`fixture.example.invalid`), the same seed gives the same bytes, and only the
standard library is used. `variant_fixtures()` adds the other shapes (the Entra
CSV, Intune JSON, an empty policy list, the administrator CSV) for the tests.
