# Linux disk space email alerts

CreoPDM stores vaults, Git history, uploads, and temporary work under `~/.local/share/CreoPDM` on the Linux host. When that filesystem fills up, adds and check-ins can fail with disk-full errors and the UI may show opaque failures. Hourly disk alerts give you time to free space before users are blocked.

This setup uses:

- **Postfix** to send mail from the server
- **`mail`** (`mailutils`) to compose messages
- A **Bash script** that checks `/` usage
- A **systemd timer** that runs the check every hour
- **Warning** at 85% and **critical** at 95%
- **State tracking** so you only get mail when the condition changes (not every hour)

Replace `admin@example.com` and `appserver.local` with your alert address and hostname.

---

## 1. Install Postfix and mail utilities

On Debian or Ubuntu:

```bash
sudo apt update
sudo apt install postfix mailutils
```

If prompted for the Postfix configuration type, choose:

```text
Internet Site
```

Use the server hostname as the system mail name, for example:

```text
creopdm.local
```

---

## 2. Configure Postfix for local applications

Accept mail only from this machine (suitable for scripts on the CreoPDM host):

```bash
sudo postconf -e 'inet_interfaces = loopback-only'
sudo postconf -e 'mydestination = $myhostname, localhost.$mydomain, localhost'
sudo postconf -e 'mynetworks = 127.0.0.0/8'
sudo postconf -e 'append_dot_mydomain = no'
```

Restart and verify:

```bash
sudo systemctl restart postfix
sudo systemctl status postfix --no-pager
```

---

## 3. Test email delivery

```bash
echo "Test email from $(hostname)" | mail -s "Server Email Test" admin@example.com
```

Check inbox and Spam. Inspect the queue and recent logs:

```bash
mailq
sudo journalctl --since "10 minutes ago" | grep -i postfix
```

A successful send usually includes `status=sent`.

**Note:** Mail sent directly from a home or lab server is often marked as spam. For production, prefer an authenticated SMTP relay (and SPF / DKIM / DMARC on your domain). The monitoring script still works the same; only Postfix’s outbound relay settings change.

---

## 4. Create the disk monitoring script

```bash
sudo nano /usr/local/sbin/disk-alert.sh
```

```bash
#!/bin/bash
# Alert when filesystem usage for / crosses warning/critical thresholds.
# Emails only on state change (normal ↔ warning ↔ critical).

EMAIL="admin@example.com"
WARNING=85
CRITICAL=95
STATEFILE="/var/tmp/disk-alert-state"

HOST=$(hostname)
USAGE=$(df / --output=pcent | tail -1 | tr -dc '0-9')
INFO=$(df -h / | tail -1)

if [ "$USAGE" -ge "$CRITICAL" ]; then
    STATE="critical"
elif [ "$USAGE" -ge "$WARNING" ]; then
    STATE="warning"
else
    STATE="normal"
fi

OLDSTATE=$(cat "$STATEFILE" 2>/dev/null || echo "normal")

if [ "$STATE" != "$OLDSTATE" ]; then
    case "$STATE" in
        warning)
            SUBJECT="WARNING: $HOST disk usage is ${USAGE}%"
            MESSAGE="Disk usage on $HOST has reached ${USAGE}% (warning ≥ ${WARNING}%). CreoPDM vaults and Git history need free space on this volume."
            ;;
        critical)
            SUBJECT="CRITICAL: $HOST disk usage is ${USAGE}%"
            MESSAGE="Disk usage on $HOST has reached ${USAGE}% (critical ≥ ${CRITICAL}%). CreoPDM adds and check-ins may fail until space is freed."
            ;;
        normal)
            SUBJECT="RECOVERED: $HOST disk usage is ${USAGE}%"
            MESSAGE="Disk usage on $HOST has returned to normal at ${USAGE}%."
            ;;
    esac

    printf "%s\n\n%s\n" "$MESSAGE" "$INFO" | mail -s "$SUBJECT" "$EMAIL"
fi

echo "$STATE" > "$STATEFILE"
```

Make it executable:

```bash
sudo chmod +x /usr/local/sbin/disk-alert.sh
```

To watch a different mount (for example a dedicated data disk), change both `df /` lines to that path (for example `df /mnt/data`).

---

## 5. Test the script

```bash
df -h /
```

Force a warning once:

```bash
sudo sed -i 's/WARNING=85/WARNING=1/' /usr/local/sbin/disk-alert.sh
sudo /usr/local/sbin/disk-alert.sh
```

Restore the threshold and clear state after the test:

```bash
sudo sed -i 's/WARNING=1/WARNING=85/' /usr/local/sbin/disk-alert.sh
sudo rm -f /var/tmp/disk-alert-state
```

---

## 6. systemd service

```bash
sudo nano /etc/systemd/system/disk-alert.service
```

```ini
[Unit]
Description=Disk Space Alert

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/disk-alert.sh
```

---

## 7. systemd timer (hourly)

```bash
sudo nano /etc/systemd/system/disk-alert.timer
```

```ini
[Unit]
Description=Check disk space hourly

[Timer]
OnBootSec=5min
OnUnitActiveSec=1h
Persistent=true

[Install]
WantedBy=timers.target
```

---

## 8. Enable monitoring

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now disk-alert.timer
systemctl list-timers disk-alert.timer
```

The timer list shows when the next check will run.

---

## 9. Manual check and logs

```bash
sudo systemctl start disk-alert.service
sudo journalctl -u disk-alert.service --no-pager
cat /var/tmp/disk-alert-state
```

State values: `normal`, `warning`, `critical`.

---

## How notifications work

The script does **not** email every hour. It emails only when the state changes:

| Usage on `/` | State |
|--------------|--------|
| Below 85% | Normal |
| 85%–94% | Warning |
| 95% or more | Critical |

Example:

```text
73% → no email
85% → warning email
88% → no additional email
95% → critical email
96% → no additional email
82% → recovery email
```

That avoids alert fatigue while still notifying you when the disk crosses a threshold or recovers—important for a CreoPDM host that grows with vaults, media adds, and Git history.
