<#
.SYNOPSIS
Exports the six Microsoft 365 files revrook reads, in one go, for one client tenant.

.DESCRIPTION
Signs in to Microsoft Graph and Exchange Online with your own administrator account
(read-only scopes; nothing in the tenant is changed) and writes into one folder:

  entra-registration.json   Graph reports/authenticationMethods/userRegistrationDetails
  secure-score.json         Graph security/secureScores (newest reading)
  intune-devices.json       Graph deviceManagement/managedDevices (no serial, IMEI or phone)
  conditional-access.json   Graph identity/conditionalAccess/policies
  directory-roles.json      Graph directoryRoles with their members
  exchange-export.csv       Exchange Online settings: DKIM, policies, mailboxes, audit, alerts

Drop the whole folder on Import evidence in revrook: each file is recognised by its
content and stored as evidence of the client you choose there. The JSON files carry
the time they were made (capturedAt), so their evidence is dated correctly.

Needs PowerShell 7 (or Windows PowerShell 5.1) and the modules
Microsoft.Graph.Authentication and ExchangeOnlineManagement:

  Install-Module Microsoft.Graph.Authentication, ExchangeOnlineManagement -Scope CurrentUser

The Graph scopes asked for are read-only: AuditLog.Read.All, SecurityEvents.Read.All,
DeviceManagementManagedDevices.Read.All, Policy.Read.All, RoleManagement.Read.Directory.
Exchange needs a role that can read the organisation settings (View-Only Organization
Management, or Global Reader). Protection alerts come from Security & Compliance
PowerShell; leave them out with -SkipAlerts when that is not available.

.PARAMETER OutputFolder
Where the six files are written. Created when missing; existing files are replaced.

.PARAMETER TenantId
The tenant to sign in to (its id or a verified domain). Optional for your own tenant.

.PARAMETER SkipExchange
Write only the five Graph files.

.PARAMETER SkipAlerts
Leave the protection alerts out of exchange-export.csv.

.EXAMPLE
./export-m365.ps1 -OutputFolder ./contoso-2026-11 -TenantId contoso.onmicrosoft.com

Download it from Import evidence in revrook (it is served at
/static/scripts/export-m365.ps1); a downloaded script may need
Unblock-File ./export-m365.ps1 before PowerShell runs it.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$OutputFolder,
    [string]$TenantId,
    [switch]$SkipExchange,
    [switch]$SkipAlerts
)

Set-StrictMode -Version 3
$ErrorActionPreference = 'Stop'

$GraphScopes = @(
    'AuditLog.Read.All',
    'SecurityEvents.Read.All',
    'DeviceManagementManagedDevices.Read.All',
    'Policy.Read.All',
    'RoleManagement.Read.Directory'
)
$Utf8 = New-Object System.Text.UTF8Encoding($false)

function Write-Utf8File([string]$Path, [string]$Text) {
    [System.IO.File]::WriteAllText($Path, $Text, $Utf8)
}

function Get-GraphPages([string]$Uri) {
    # Every page of a Graph list, as one answer with the context of the first page.
    $first = Invoke-MgGraphRequest -Method GET -Uri $Uri -OutputType Hashtable
    $items = New-Object System.Collections.ArrayList
    $page = $first
    while ($true) {
        if ($page.ContainsKey('value')) { [void]$items.AddRange(@($page['value'])) }
        $next = $page['@odata.nextLink']
        if (-not $next) { break }
        $page = Invoke-MgGraphRequest -Method GET -Uri $next -OutputType Hashtable
    }
    return [ordered]@{
        '@odata.context' = $first['@odata.context']
        'capturedAt'     = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
        'value'          = $items.ToArray()
    }
}

function Save-Graph([string]$Name, [string]$Uri) {
    $answer = Get-GraphPages $Uri
    $path = Join-Path $OutputFolder $Name
    Write-Utf8File $path ($answer | ConvertTo-Json -Depth 30)
    Write-Host ("{0,-26} {1} records" -f $Name, @($answer['value']).Count)
}

function Flag($Value) {
    if ($null -eq $Value) { return '' }
    if ([bool]$Value) { return 'true' }
    return 'false'
}

function Exchange-Row([hashtable]$Cells) {
    $row = [ordered]@{}
    foreach ($column in $ExchangeColumns) { $row[$column] = '' }
    foreach ($key in $Cells.Keys) { $row[$key] = $Cells[$key] }
    return [pscustomobject]$row
}

$ExchangeColumns = @(
    'record_type', 'domain', 'enabled', 'policy_type', 'auto_forwarding_mode',
    'mailbox', 'recipient_type', 'forwarding_external', 'account_enabled',
    'unified_audit_log_enabled', 'audit_disabled', 'alert_kind', 'disabled',
    'recipient_count', 'last_acknowledged'
)
# Default alert policies of Microsoft 365 and the kind revrook reads them as. Only
# these are written; there is no default policy for risky sign-ins (that alert
# lives in Entra ID Protection), so that control stays Not checked from this file.
$AlertKinds = @{
    'Elevation of Exchange admin privilege' = 'admin-role'
    'Suspicious email forwarding activity'  = 'forwarding-rule'
    'Creation of forwarding/redirect rule'  = 'forwarding-rule'
}
$RecipientTypes = @{
    'UserMailbox'      = 'user'
    'SharedMailbox'    = 'shared'
    'RoomMailbox'      = 'room'
    'EquipmentMailbox' = 'equipment'
}

New-Item -ItemType Directory -Force -Path $OutputFolder | Out-Null

# --- Microsoft Graph ------------------------------------------------------------
Import-Module Microsoft.Graph.Authentication
$connect = @{ Scopes = $GraphScopes; NoWelcome = $true }
if ($TenantId) { $connect['TenantId'] = $TenantId }
Connect-MgGraph @connect

$graph = 'https://graph.microsoft.com/v1.0'
Save-Graph 'entra-registration.json' "$graph/reports/authenticationMethods/userRegistrationDetails"
Save-Graph 'secure-score.json' "$graph/security/secureScores?`$top=1"
$deviceFields = 'id,complianceState,operatingSystem,osVersion,lastSyncDateTime,managementAgent,ownerType,userPrincipalName,isEncrypted'
Save-Graph 'intune-devices.json' "$graph/deviceManagement/managedDevices?`$select=$deviceFields"
Save-Graph 'conditional-access.json' "$graph/identity/conditionalAccess/policies"
Save-Graph 'directory-roles.json' "$graph/directoryRoles?`$expand=members"
Disconnect-MgGraph | Out-Null

if ($SkipExchange) {
    Write-Host "Done: five Graph files in $OutputFolder (Exchange skipped)."
    return
}

# --- Exchange Online ------------------------------------------------------------
Import-Module ExchangeOnlineManagement
$exchange = @{ ShowBanner = $false }
if ($TenantId) { $exchange['Organization'] = $TenantId }
Connect-ExchangeOnline @exchange

$rows = New-Object System.Collections.ArrayList
foreach ($config in @(Get-DkimSigningConfig)) {
    [void]$rows.Add((Exchange-Row @{ record_type = 'dkim'; domain = $config.Domain; enabled = (Flag $config.Enabled) }))
}
# The Defender for Office 365 policies exist only with that licence; a missing
# cmdlet leaves the policy out, so its control stays Not checked instead of failing.
$policies = @(
    @{ Command = 'Get-AntiPhishPolicy'; Type = 'anti-phish' },
    @{ Command = 'Get-SafeLinksPolicy'; Type = 'safe-links' },
    @{ Command = 'Get-SafeAttachmentPolicy'; Type = 'safe-attachments' }
)
foreach ($policy in $policies) {
    if (-not (Get-Command $policy.Command -ErrorAction SilentlyContinue)) { continue }
    foreach ($item in @(& $policy.Command)) {
        # The switch has another name in each policy type; a policy without one
        # is left out rather than guessed.
        $switch = @('Enabled', 'Enable', 'EnableSafeLinksForEmail', 'IsEnabled') |
            Where-Object { $item.PSObject.Properties[$_] } | Select-Object -First 1
        if (-not $switch) { continue }
        [void]$rows.Add((Exchange-Row @{ record_type = 'policy'; policy_type = $policy.Type; enabled = (Flag $item.$switch) }))
    }
}
foreach ($item in @(Get-HostedOutboundSpamFilterPolicy)) {
    [void]$rows.Add((Exchange-Row @{
        record_type = 'policy'; policy_type = 'outbound-spam'; enabled = 'true'
        auto_forwarding_mode = ([string]$item.AutoForwardingMode).ToLowerInvariant()
    }))
}
# Mailboxes by their directory id: no address leaves this script, and revrook
# replaces the id with the client's pseudonym anyway.
$disabled = @{}
foreach ($user in @(Get-User -ResultSize Unlimited)) {
    $disabled[[string]$user.ExternalDirectoryObjectId] = [bool]$user.AccountDisabled
}
foreach ($box in @(Get-EXOMailbox -ResultSize Unlimited -Properties ForwardingSmtpAddress, ForwardingAddress, RecipientTypeDetails, ExternalDirectoryObjectId)) {
    $type = $RecipientTypes[[string]$box.RecipientTypeDetails]
    if (-not $type) { continue }
    $id = [string]$box.ExternalDirectoryObjectId
    $enabled = if ($disabled.ContainsKey($id)) { Flag (-not $disabled[$id]) } else { '' }
    $forwarding = [bool]($box.ForwardingSmtpAddress -or $box.ForwardingAddress)
    [void]$rows.Add((Exchange-Row @{
        record_type = 'mailbox'; mailbox = $id; recipient_type = $type
        forwarding_external = (Flag $forwarding); account_enabled = $enabled
    }))
}
$audit = Get-AdminAuditLogConfig
$organisation = Get-OrganizationConfig
[void]$rows.Add((Exchange-Row @{
    record_type = 'audit'
    unified_audit_log_enabled = (Flag $audit.UnifiedAuditLogIngestionEnabled)
    audit_disabled = (Flag $organisation.AuditDisabled)
}))
Disconnect-ExchangeOnline -Confirm:$false | Out-Null

if (-not $SkipAlerts) {
    Connect-IPPSSession
    foreach ($alert in @(Get-ProtectionAlert)) {
        $kind = $AlertKinds[[string]$alert.Name]
        if (-not $kind) { continue }
        [void]$rows.Add((Exchange-Row @{
            record_type = 'alert'; alert_kind = $kind; disabled = (Flag $alert.Disabled)
            recipient_count = [string]@($alert.NotifyUser | Where-Object { $_ }).Count
        }))
    }
    Disconnect-ExchangeOnline -Confirm:$false | Out-Null
}

# -NoTypeInformation is needed by Windows PowerShell 5.1 and only warns on 7.
$csv = ($rows | ConvertTo-Csv -NoTypeInformation -WarningAction SilentlyContinue) -join "`n"
Write-Utf8File (Join-Path $OutputFolder 'exchange-export.csv') ($csv + "`n")
Write-Host ("{0,-26} {1} rows" -f 'exchange-export.csv', $rows.Count)
Write-Host "Done: drop the folder $OutputFolder on Import evidence in revrook."
