# Migration: AWS EC2 → Hostinger VPS (KVM 2)

**Status:** planned, not executed. Written 2026-09-02.
**Source:** `13.235.238.99` (AWS ap-south-1, 2 vCPU / 1.9 GB / 20 GB).
**Target:** Hostinger VPS **KVM 2** (2 vCPU / 8 GB RAM / 100 GB NVMe, x86_64).
**Agreed downtime window:** 15–30 min.

> Prerequisite: this assumes the **2026-09-02 DB consolidation** is in place — Postgres
> and PgBouncer run as containers on the app box. If you are reading this before that,
> stop; migrating two coupled instances is a different and much worse job.

---

## 1. Why this is a straightforward move

| Factor | Status |
|---|---|
| **Architecture** | KVM 2 is **x86_64**, same as now → **no image rebuilds.** All four images (`ngu-backend`, `ngu-frontend`, `ngu-admin`, `ngu-whisper`) are `linux/amd64` and pull as-is. This is the single biggest thing that could have gone wrong, and it doesn't. |
| **AWS coupling** | **None at runtime.** `USE_S3=False` and `USE_CLOUDINARY=True` — media is on Cloudinary, static is served locally from a volume. Nothing to re-point. |
| **Data volume** | **~282 MB total.** Transfers in a couple of minutes over the wire. |
| **Topology** | One box → one box. No VPC, no private-IP link, no security-group pairing. |
| **RAM** | 1.9 GB → **8 GB**. This move *fixes* the standing memory pressure (see §7). |

Everything the app needs is: Docker images (public on Docker Hub), five volumes, two env
files, one nginx config, and the TLS certs.

---

## 2. Pre-flight checks — do these BEFORE committing

### 2.1 ⚠️ Outbound SMTP on port 587 — the one that can silently break orders

The app sends order confirmations through **Gmail SMTP (`smtp.gmail.com:587`)**. Many VPS
providers block outbound 25/465/587 by default to curb spam, **and the failure is silent**:
`orders/emails.py` sends on a background `threading.Thread`, so a blocked port means
customers stop receiving order confirmations while the site looks perfectly healthy.

Test on the new VPS **before migrating anything**:

```bash
# should connect and return a 220 banner within a second or two
timeout 8 curl -v --url smtp://smtp.gmail.com:587 2>&1 | head -20
# or:
python3 -c "import smtplib; s=smtplib.SMTP('smtp.gmail.com',587,timeout=8); print(s.ehlo()); s.quit()"
```

If it hangs or refuses: open a Hostinger support ticket to unblock 587, or switch to an
API-based sender (Brevo / Resend / SendGrid HTTP API) which uses 443 and cannot be blocked.
**Do not migrate until this is resolved** — silently losing order emails is worse than a
delayed migration.

### 2.2 Data-centre location

Customers are in India and the current box is Mumbai (`ap-south-1`). Pick Hostinger's
**India location** — a US/EU region adds ~150–250 ms to every API call, on a storefront
whose homepage already fires five API calls in one `Promise.all`.

### 2.3 Confirm the KVM 2 spec

Verify on the provisioned box before planning memory limits:
```bash
nproc; free -h; df -h /; uname -m   # expect 2, ~8 GB, ~100 GB, x86_64
```

### 2.4 Lower DNS TTL — 24–48 h ahead

At the registrar, drop the TTL on `nidhigrahudyog.com` (and `www`) to **300 s** at least a
day before cutover. Otherwise the old IP stays cached for whatever the current TTL is and
the "15-minute window" becomes hours for some users.

---

## 3. What has to move

### Docker volumes (~282 MB)

| Volume | Size | Contents | If lost |
|---|---|---|---|
| `ngu_pg_data` | 70 MB | **The database.** | Catastrophic |
| `ngu_media_data` | 36 MB, 1494 files | Product/category images served locally | Broken images sitewide |
| `ngu_static_data` | 12 MB | Django static (`USE_S3=False`, so this is live) | Unstyled admin |
| `ngu_private_media_data` | 116 KB, 25 files | **Admin-only delivery bills.** Not on Cloudinary, not in the DB. | **Permanently gone** |
| `ngu_redis_data` | 64 MB | Cache + throttle state | Harmless — rebuilds itself |

> `ngu_media_data` and `ngu_private_media_data` are the two that catch people out.
> Neither is reconstructible from Cloudinary or from a database dump.

### Host-level state (none of it in Docker)

- `~/NGU/docker-compose.prod.yml`
- `~/NGU/.env.backend` — **all secrets**, never in git
- `~/NGU/.env` — `POSTGRES_PASSWORD` for Compose interpolation (added 2026-09-02)
- `~/NGU/pg_backup.sh` + `ngu-pg-backup.{service,timer}`
- `/etc/nginx/conf.d/ngu.conf` — TLS vhost for all four hostnames
- `/etc/letsencrypt/` — two cert lineages, **expiring 2026-10-15**
- `certbot-renew.{service,timer}` (dockerized certbot)
- `/swapfile` (2 GB) + its `/etc/fstab` entry — less critical at 8 GB, still worth having

---

## 4. Runbook

### Phase A — Build the new box (no downtime; old site stays live)

```bash
# 4.1 Harden SSH first. Hostinger ships root+password by default.
ssh-copy-id root@<NEW_IP>
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin prohibit-password/;
        s/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart sshd

# 4.2 Docker + Compose v2
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker
docker compose version     # must be v2 ("docker compose", not "docker-compose")

# 4.3 Firewall. ⚠ NO SECURITY GROUPS HERE — this is your only network layer.
#    Docker writes its own iptables rules (DOCKER-USER) that BYPASS ufw, so any
#    port published on 0.0.0.0 is exposed regardless of ufw. Our compose binds
#    backend/frontend/admin/postgres to 127.0.0.1 and does not publish pgbouncer
#    at all — keep it that way and never "helpfully" remove a 127.0.0.1: prefix.
ufw default deny incoming; ufw default allow outgoing
ufw allow 22/tcp; ufw allow 80/tcp; ufw allow 443/tcp
ufw enable
ss -tlnp   # verify ONLY 22/80/443 listen on 0.0.0.0; everything else on 127.0.0.1

# 4.4 Swap
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab

# 4.5 nginx + certbot
dnf install -y nginx || apt install -y nginx
systemctl enable --now nginx
```

Then copy the **config** across (not the data yet):

```bash
# from your workstation
scp -i my-pem.pem ec2-user@13.235.238.99:~/NGU/docker-compose.prod.yml  /tmp/
scp -i my-pem.pem ec2-user@13.235.238.99:~/NGU/pg_backup.sh             /tmp/
ssh  -i my-pem.pem ec2-user@13.235.238.99 'sudo cat /etc/nginx/conf.d/ngu.conf' > /tmp/ngu.conf
# .env.backend and .env contain secrets — move them directly, never through a repo
scp -i my-pem.pem ec2-user@13.235.238.99:~/NGU/.env.backend             /tmp/
scp -i my-pem.pem ec2-user@13.235.238.99:~/NGU/.env                     /tmp/

scp /tmp/{docker-compose.prod.yml,pg_backup.sh,.env.backend,.env} root@<NEW_IP>:/root/NGU/
scp /tmp/ngu.conf root@<NEW_IP>:/etc/nginx/conf.d/ngu.conf
chmod 600 /root/NGU/.env /root/NGU/.env.backend
```

> If you run as `root` on Hostinger rather than `ec2-user`, update the absolute paths in
> `pg_backup.sh` and `ngu-pg-backup.service` (`/home/ec2-user/NGU` → `/root/NGU`).

Pre-pull images so cutover isn't waiting on Docker Hub:
```bash
cd /root/NGU && docker compose -f docker-compose.prod.yml pull
```

### Phase B — Cutover (the 15–30 min window)

```bash
### ON OLD BOX — stop writes, snapshot everything
cd ~/NGU
docker compose -f docker-compose.prod.yml stop backend scheduler   # writes stop here
~/NGU/pg_backup.sh                                                 # fresh verified dump
docker compose -f docker-compose.prod.yml down                     # volumes survive `down`

# tar every volume (run as root; paths are under /var/lib/docker/volumes)
sudo tar czf /tmp/ngu_volumes.tgz -C /var/lib/docker/volumes \
  ngu_pg_data ngu_media_data ngu_static_data ngu_private_media_data
sudo tar czf /tmp/ngu_certs.tgz -C /etc letsencrypt
sudo chown ec2-user: /tmp/ngu_volumes.tgz /tmp/ngu_certs.tgz
md5sum /tmp/ngu_volumes.tgz /tmp/ngu_certs.tgz    # record these

### TRANSFER (via workstation; or scp directly if you put a key on the new box)
scp -i my-pem.pem ec2-user@13.235.238.99:/tmp/ngu_{volumes,certs}.tgz /tmp/
scp /tmp/ngu_{volumes,certs}.tgz root@<NEW_IP>:/tmp/
# re-check md5sum on the new box before proceeding

### ON NEW BOX — restore
cd /root/NGU
docker compose -f docker-compose.prod.yml up -d postgres   # creates volume dirs
docker compose -f docker-compose.prod.yml down
tar xzf /tmp/ngu_volumes.tgz -C /var/lib/docker/volumes
tar xzf /tmp/ngu_certs.tgz -C /etc
docker compose -f docker-compose.prod.yml up -d
```

`redis_data` is deliberately not copied — it is cache and throttle state, and rebuilds
itself. Skipping it avoids carrying stale keys onto the new box.

### Phase C — Verify BEFORE touching DNS

The site is still live on the old IP at this point, so take your time.

```bash
# hit the new box directly, bypassing DNS
curl -s -o /dev/null -w "%{http_code}\n" --resolve nidhigrahudyog.com:443:<NEW_IP> \
  https://nidhigrahudyog.com/api/products/

for p in /api/products/ /api/products/sections/ /api/categories/ /api/combos/ \
         /api/reviews/featured/ /api/health/ / /panel/; do
  printf "%-28s %s\n" "$p" "$(curl -s -o /dev/null -w '%{http_code}' \
    --resolve nidhigrahudyog.com:443:<NEW_IP> https://nidhigrahudyog.com$p)"
done

# data intact? compare against the old box
docker exec ngu-postgres psql -U KaushalJainAI -d ngu_db -t -A -c \
 "select 'orders='||(select count(*) from orders_order)
      ||' products='||(select count(*) from products_product)
      ||' users='||(select count(*) from users_user)
      ||' invoices='||(select count(*) from orders_invoice);"

docker exec ngu-backend python manage.py migrate --check   # expect exit 0
```

Also confirm, because these are the things a move breaks quietly:
- [ ] **SMTP 587 reachable** (§2.1) — send a real test email
- [ ] Product **images render** (media volume came across)
- [ ] `/panel/` loads *and* logs in
- [ ] An **admin delivery bill** downloads (private_media volume came across)
- [ ] Razorpay **key mode** still `rzp_live_`:
      `docker exec ngu-backend python manage.py shell -c "from django.conf import settings; print(settings.RAZORPAY_TEST_MODE, settings.RAZORPAY_KEY_ID[:9])"`

### Phase D — DNS flip

Point `nidhigrahudyog.com` + `www` A records at `<NEW_IP>`.

**Fix the standing DNS drift at the same time** — `nidhimasala.com` currently points at
`3.33.251.168` (not your server at all) and `www.nidhimasala.com` has no A record. Point
all four names at `<NEW_IP>` and the second domain starts working for the first time.

After DNS propagates, renew certs so future auto-renewals validate against the new IP:
```bash
certbot renew --dry-run     # must pass before you trust the timer
```
Restore the systemd units (`certbot-renew`, `ngu-pg-backup`) and re-run `systemctl
enable --now` on both timers. Raise the DNS TTL back to ~3600 once settled.

### Phase E — Decommission

Keep the AWS boxes **stopped, not terminated**, for at least a week of real traffic
including one real order. Stopped EC2 costs only EBS storage (a few dollars) — cheap
insurance. Then terminate `13.235.238.99`, `13.201.33.243`, and release the Elastic IPs
(unattached EIPs bill separately).

---

## 5. Rollback

Valid until you terminate the old box:

1. Point DNS back at `13.235.238.99` (this is why the low TTL matters).
2. On the old box: `cd ~/NGU && docker compose -f docker-compose.prod.yml up -d`.

Anything written on the new box after cutover is lost on rollback — so decide within the
window, before real orders land, or plan to reconcile by hand.

---

## 6. Post-move: things that must be updated

- **`CLAUDE.md`** — the entire *Production stack* section, every `13.235.238.99`
  reference, the SSH command, and the "Do NOT run tests against production" IPs.
- **`DEPLOYMENT.md`** — currently describes a two-instance AWS topology with security
  groups. Most of it becomes wrong; consider superseding it with this document.
- **Razorpay dashboard** — the webhook URL is domain-based, so the IP change is
  transparent. ⚠ But `RAZORPAY_LIVE_WEBHOOK_SECRET` is **still unset** (see CLAUDE.md);
  the move is a natural moment to finally set it.
- **Google OAuth** — authorized origins are domain-based; no change needed.
- **Cloudinary / OpenRouter** — no IP allowlists in play; no change needed.

---

## 7. What 8 GB unlocks (do these AFTER the move is stable)

The current box is the binding constraint on the whole stack. On 8 GB:

1. **Raise the `backend` memory limit 512 M → 1.5 G.** It currently runs at 74–97% of its
   cap and swaps. This is `SCALING_AUDIT.md`'s top recommendation — it was *invalid* on the
   1.9 GB box (that RAM did not exist) and becomes correct on this one.
2. **Add gunicorn `--preload`.** Saves ~150–200 MB by sharing the langchain heap across
   workers via copy-on-write instead of building it per worker.
3. **Consider more gunicorn workers.** Still only 2 vCPU, so CPU stays the limit — raise
   workers for I/O concurrency, not throughput.
4. **Give Postgres more.** `shared_buffers` is pinned at a deliberately small 128 MB for the
   1.9 GB box; 512 MB–1 GB is reasonable at 8 GB.
5. **Off-box backups.** Still the largest open risk: dumps live on the same disk as the
   database. Push `~/NGU/backups/*.dump.gz` to object storage nightly.

---

## 8. Cost

Two EC2 instances (~2 × t3.small-class) → one KVM 2, which is typically **$7–10/month**.
The saving is real, but the bigger win is 8 GB instead of 1.9 GB — you are paying less for
roughly four times the memory, and it removes the constraint that currently shapes every
performance decision in `SCALING_AUDIT.md`.
