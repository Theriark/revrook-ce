"""The usual next step for a control that is not met, one plain sentence each.

A finding of the quarterly review prints it under "Usual next step" when the
technician wrote no recommendation of their own; what the technician writes always
takes its place. The sentences are general: they say what normally closes the gap the
control names, not what was decided for one client. They are not part of the ruleset
(changing one changes no score and no snapshot), and every control of the library has
one (tests/test_reports.py).
"""

# A control that passes on evidence that has grown old needs fresh evidence, not a fix.
REFRESH_EVIDENCE = (
    "Import a fresh export: the last check passed, but its evidence is out of date."
)

NEXT_STEPS = {
    "PC-ACC-01": (
        "Register every active staff account for multi-factor sign-in, starting "
        "with the accounts that have none."
    ),
    "PC-ACC-02": (
        "Register every administrator account for multi-factor sign-in before "
        "anything else."
    ),
    "PC-ACC-03": (
        "Turn on security defaults, or a Conditional Access policy that requires "
        "multi-factor sign-in for all users, so that it is enforced and not only "
        "registered."
    ),
    "PC-ACC-04": (
        "Block the legacy sign-in methods (IMAP, POP, basic SMTP) for all users, "
        "with security defaults or a Conditional Access policy."
    ),
    "PC-ACC-05": (
        "Keep the Global Administrator role to a few named people, each on their "
        "own account, and give everyone else a narrower role."
    ),
    "PC-ACC-06": (
        "Disable the accounts that have not signed in for more than 90 days, once "
        "the business confirms they are no longer needed."
    ),
    "PC-ACC-07": (
        "Remove the guest accounts that have been inactive for more than 180 days "
        "and let only administrators invite guests."
    ),
    "PC-ACC-08": (
        "Create an emergency (break-glass) administrator account, keep its "
        "credentials sealed and offline, and write down who may use it and when."
    ),
    "PC-DEV-01": (
        "Enrol every active device in device management, so that the inventory and "
        "the management tool list the same devices."
    ),
    "PC-DEV-02": (
        "Install the pending critical updates and set updates to install by "
        "themselves within 30 days of release."
    ),
    "PC-DEV-03": (
        "Upgrade or replace the devices whose operating system is past the vendor's "
        "end of support."
    ),
    "PC-DEV-04": (
        "Turn on disk encryption on the devices that do not have it and keep the "
        "recovery keys in a managed place."
    ),
    "PC-DEV-05": (
        "Bring the devices that are not compliant back into the compliance "
        "baseline, or retire them."
    ),
    "PC-DEV-06": (
        "Assign every device a configuration profile that locks the screen after at "
        "most 15 minutes without use."
    ),
    "PC-DEV-07": (
        "Take local administrator rights away from daily accounts and keep a "
        "separate managed administrator account for installs."
    ),
    "PC-END-01": (
        "Turn real-time anti-malware protection back on, or install it, on the "
        "devices where it is off or missing."
    ),
    "PC-END-02": (
        "Fix the devices whose protection signatures are more than three days old: "
        "they are usually offline or failing to update."
    ),
    "PC-END-03": (
        "Review and close the open high-severity detections, each with an owner and "
        "an outcome."
    ),
    "PC-END-04": (
        "Turn on tamper protection, so that neither a user nor malware can switch "
        "the protection off."
    ),
    "PC-END-05": (
        "Remove the remote-access software that is not approved and block its "
        "installation."
    ),
    "PC-EML-01": (
        "Publish one SPF record on each mail domain that lists your sending "
        "services and ends in ~all or -all."
    ),
    "PC-EML-02": (
        "Turn on DKIM signing for each mail domain and publish its selector records "
        "in DNS."
    ),
    "PC-EML-03": (
        "Publish a DMARC record with a reporting address, then move its policy from "
        "none to quarantine or reject once the reports are clean."
    ),
    "PC-EML-04": (
        "Turn on the anti-phishing, safe links and safe attachments policies, or "
        "the standard preset protection policy, where the licence includes them."
    ),
    "PC-EML-05": (
        "Set automatic forwarding to outside addresses to off in the outbound spam "
        "policy and remove the mailbox rules that forward outside."
    ),
    "PC-EML-06": (
        "Block sign-in on the accounts of shared mailboxes: people reach them "
        "through their own account."
    ),
    "PC-EML-07": (
        "Give staff a report button in their mail program, or a named address, for "
        "suspicious email, and tell them about it."
    ),
    "PC-BCK-01": (
        "Fix the backup jobs that fail or are missing, so that every in-scope "
        "system has a successful backup within its schedule."
    ),
    "PC-BCK-02": (
        "Cover Exchange, OneDrive, SharePoint and Teams with a backup that is "
        "independent of Microsoft 365."
    ),
    "PC-BCK-03": (
        "Run a test restore for each backup product or class of system, record its "
        "date and result, and repeat it every quarter."
    ),
    "PC-BCK-04": (
        "Keep at least one backup copy immutable or offline, where a compromised "
        "administrator account cannot delete it."
    ),
    "PC-BCK-05": "Encrypt the backup jobs and keep at least 30 days of retention.",
    "PC-BCK-06": (
        "Write down how fast each system must be back, how much data may be lost, "
        "and the steps to recover it."
    ),
    "PC-NET-01": (
        "Update the firewall firmware to a supported release, and replace a "
        "firewall that is past its end of support."
    ),
    "PC-NET-02": (
        "Close the inbound rules that open remote desktop, file sharing, databases "
        "or management ports to the whole internet: use a VPN or limit the source "
        "addresses."
    ),
    "PC-NET-03": (
        "Switch off management of the firewall from the internet side and change "
        "any default login."
    ),
    "PC-NET-04": (
        "Move the Wi-Fi networks to WPA2 or WPA3 and separate the guest network "
        "from the business network."
    ),
    "PC-NET-05": "Turn on web or DNS filtering on every device.",
    "PC-LOG-01": (
        "Turn on the unified audit log for the tenant and make sure mailbox "
        "auditing is not disabled."
    ),
    "PC-LOG-02": (
        "Keep the audit logs long enough to investigate an incident: raise the "
        "retention or export the logs to an archive."
    ),
    "PC-LOG-03": (
        "Send security alerts to a named person who acknowledges them, not to a "
        "mailbox nobody reads."
    ),
    "PC-LOG-04": (
        "Enable the alerts for the riskiest changes: a new administrator role, a "
        "new mail forwarding rule and a risky sign-in."
    ),
    "PC-LOG-05": (
        "Have a named person review the security logs or reports each month and "
        "keep a dated note of every review."
    ),
    "PC-LOG-06": (
        "Send the logs of the firewall and of the servers to one central place."
    ),
    "PC-GOV-01": (
        "Name the person who owns security and write a short security policy that "
        "the business approves."
    ),
    "PC-GOV-02": (
        "Write down the main risks to the business, how likely and how serious each "
        "is and what is done about it, and review the list every year."
    ),
    "PC-GOV-03": (
        "Enrol the staff who have no completion in the last 12 months in security "
        "awareness training."
    ),
    "PC-GOV-04": (
        "Disable the account of a leaver on the last working day, and at the latest "
        "within three days."
    ),
    "PC-GOV-05": (
        "Write an incident response plan with the contacts to call, and run one "
        "exercise of it."
    ),
    "PC-GOV-06": (
        "Review the third-party apps that can reach the tenant and keep a register "
        "of the suppliers that handle your data; remove what is no longer used."
    ),
    "PC-GOV-07": (
        "List where important and personal data is kept, who can reach it and who "
        "owns it."
    ),
}
