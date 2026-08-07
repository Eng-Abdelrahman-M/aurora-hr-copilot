# Data Security Policy — Aurora Dynamics

Document ID: POL-SEC-005 · Owner: Security Engineering · Last revised: 2026-03-01

## 1. Devices

- Only **company-issued, MDM-enrolled devices** may access production systems,
  customer data, or the corporate VPN.
- Personal devices may access email and Slack only through the mobile apps
  with MFA enabled; storing customer data on personal devices is prohibited.
- Full-disk encryption and automatic screen lock (max 5 minutes) are enforced
  by MDM and must not be disabled.

## 2. Authentication

- **MFA is mandatory** for all company accounts.
- Passwords must be generated and stored in the company password manager.
- Sharing credentials is prohibited, including with other employees.

## 3. Networks and remote access

- When working outside a company office, connect through the **company VPN**
  before accessing internal systems.
- **Public Wi-Fi** (cafés, airports, hotels) may be used **only with the VPN
  active**; captive portals may be completed before connecting the VPN.
- Home routers must use WPA2 or better with a non-default password.

## 4. Working while traveling or abroad

- Devices must never be left unattended in public places or checked luggage.
- For trips abroad longer than 30 days, notify Security Engineering so export
  control and device posture can be reviewed (see Remote Work Policy
  POL-RW-002 section 3).
- In high-risk countries (list maintained by Security), loaner laptops are
  issued instead of primary devices.

## 5. Data handling

- Customer data lives only in approved systems of record; exporting it to
  spreadsheets or personal storage is prohibited.
- Confidential documents are shared via access-controlled links, never as
  attachments to external parties.

## 6. Incident reporting

Report lost devices, suspected phishing, or any data exposure to
security@aurora.example **within 24 hours** of discovery. Early reporting is
never penalized; late reporting may be.
