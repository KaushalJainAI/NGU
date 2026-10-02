# AWS Migration & Connectivity Troubleshooting Pattern

This document captures the pattern used to resolve the production downtime on 2026-04-19. Use this as a first-response guide for future IP resets or credit exhaustion events in AWS.

## 1. The "Pattern" for SSH Access
When an instance IP change causes `Connection Refused` on Port 22:

1. **Clear Stale Host Keys**: Windows remembers the identity of the *old* server at that IP. Wipe it.
   ```powershell
   ssh-keygen -R <New_IP_Address>
   ```
2. **Use Native Shells**: Avoid Git Bash (MINGW64) during diagnostics. Use **PowerShell** or **CMD** as they interact more reliably with Windows' native OpenSSH service.
3. **Raw IP Access**: Do not rely on DNS hostnames during an outage. Connect directly via the Public IPv4.

## 2. The "502 Bad Gateway" Root Cause Chain
A 502 error in this architecture is rarely an Nginx bug; it is a service dependency failure:
1. **The Trigger**: Database IP changes.
2. **The Result**: Backend fails to connect -> Backend fails health check.
3. **The Cascade**: Frontend (`depends_on: backend`) never starts -> Port 3000 stays closed.
4. **The 502**: Host Nginx finds no listener on Port 3000 and throws a 502.

## 3. Environment Variable Persistence
**CRITICAL**: Docker Compose often caches environment variables. Modifying `.env` is not enough.
- **Fix**: You MUST run `docker-compose down` followed by `docker-compose up -d`. A simple `restart` will often keep the old, broken IP in memory.

## 4. Security Group Dependencies
When the **Deployment Server** IP changes, you must update the **Inbound Rules** on the **Database Server**:
- **Protocol**: TCP
- **Port**: 6432 (PgBouncer) / 5432 (Postgres)
- **Source**: `<New_Deployment_Server_IP>/32`

## 5. Directory Mapping
Always ensure the `.env` is placed in the specific service directory (e.g., `~/NGU/Backend/.env`) rather than the root, as the Docker Compose files are mapped to that specific path.

## 6. Resolving `ERR_TOO_MANY_REDIRECTS`
This error usually indicates a loop between Nginx and Django regarding HTTPS.
1. **The Loop**: Browser (HTTPS) -> Nginx -> Django (thinks it's HTTP) -> Redirect to HTTPS -> Loop.
2. **Fix**:
   - In `ngu.conf`, ensure `proxy_set_header X-Forwarded-Proto https;` is explicitly set.
   - In `settings.py`, ensure `SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')` is defined.
   - In `.env.backend`, set `SECURE_SSL_REDIRECT=False` if Nginx handles SSL.
   - Ensure `USE_X_FORWARDED_HOST=True` in `settings.py`.

## 7. SSL Certificate Management
When the IP resets, Certbot may need to re-verify the domain. If you suspect SSL issues:
- Run `sudo certbot certificates` to check status.
- Use `sudo certbot --nginx --force-renewal -d <domain>` to refresh the certificate and Nginx binding.
