# Deployment

The production instance runs on a single **Oracle Cloud Always Free** Ampere A1
VM (arm64, 4 OCPU / 24 GB RAM) at no cost. GitHub Actions ships every green
commit on `main` to it, and the deploy rolls itself back if the new version
fails its health checks.

```text
                 HTTPS (Let's Encrypt, HTTP/3)
 Browser ──────────────────────────────► Caddy ──► nginx (SPA + /api proxy, adds X-API-Key)
                                                       │
                                     private network   ▼
                                     172.28.0.0/24   FastAPI (uvicorn) ──► Groq API
                                                       │
                                                       ├──► PostgreSQL 16 (volume, nightly pg_dump)
                                                       └──► FAISS index (volume)

 git push ─► CI (lint, types, migrations, tests, evals)
               └─► Deploy: build arm64 images ─► GHCR ─► Trivy scan ─► SSH: deploy.sh ─► smoke test
                                                                            └─ unhealthy? roll back
```

| Concern | How it is handled |
|---|---|
| TLS | Caddy obtains and renews certificates; HTTP redirects to HTTPS; HSTS |
| Exposure | Only Caddy publishes ports (80/443). nginx, the API and Postgres stay on the private network; the API also listens on the host's loopback for admin calls |
| Secrets | Only in `/opt/rag/.env` on the server (mode 600). GitHub holds just the SSH deploy key |
| Admin routes | nginx returns 403 for `POST /api/index-schema`; call it over SSH instead |
| Abuse / cost | Per-IP limit of 10 queries/minute, keyed on the real client IP (the API trusts `X-Forwarded-For` only from the proxy subnet); exact and semantic LLM caches; Groq free tier, so the worst case is a 429, never a bill |
| Images | Built natively for arm64, tagged by commit, SBOM + provenance attached, blocked on critical fixable CVEs; frontend runs as non-root nginx |
| Containers | `no-new-privileges`, memory limits, log rotation, healthchecks, `restart: unless-stopped` |
| Migrations | Applied by the backend entrypoint on start (`alembic upgrade head`) |
| Rollback | Automatic on failed health or smoke checks; manual with one command |
| Fresh data | Weekdays at 22:30 UTC, `app.cli refresh` adds new prices, statements and 13F filings; stored rows are skipped |
| Backups | Nightly `pg_dump` (custom format), 7 days kept |
| Monitoring | UptimeRobot on `/api/health`, which checks the database too; JSON logs with request IDs; the in-app Observability dashboard |

Files involved: [docker-compose.prod.yml](../docker-compose.prod.yml),
[deploy/](../deploy), [.github/workflows/deploy.yml](../.github/workflows/deploy.yml),
[.env.production.example](../.env.production.example).

## First-time setup

About an hour, most of it waiting on the cloud console.

### 1. Accounts

1. **Groq**: create an API key at <https://console.groq.com/keys>. Keep it out
   of chats, commits and screenshots. It only goes in the server's `.env`.
2. **DuckDNS** (free hostname): sign in at <https://www.duckdns.org> and claim
   a subdomain, e.g. `yourname-rag.duckdns.org`. You set its IP in step 2.
3. **Oracle Cloud**: sign up at <https://www.oracle.com/cloud/free/>. A card is
   needed for verification only. Then:
   - Upgrade the account to **Pay As You Go**. Always Free resources stay free,
     but Oracle stops reclaiming "idle" free VMs. Add a **budget alert** (e.g.
     $1) under Billing so any accidental paid resource is flagged at once.

### 2. The VM

1. Compute → Instances → Create:
   - Image **Ubuntu 24.04**, shape **VM.Standard.A1.Flex**, 4 OCPU / 24 GB.
     If it says "out of capacity", retry later or try another availability domain.
   - Add your SSH public key.
2. Networking → the VM's subnet → Security List → add **ingress** rules for
   TCP 80, TCP 443 and UDP 443 from `0.0.0.0/0`.
3. Reserve the public IP (Networking → Reserved Public IPs) so it never changes,
   and set it as the IP of your DuckDNS subdomain.
4. On the VM:
   ```bash
   curl -fsSLO https://raw.githubusercontent.com/shreyescodes/RAG-Data-Platform/main/deploy/server-setup.sh
   less server-setup.sh                 # read before running
   sudo bash server-setup.sh deploy
   ```
   This installs Docker, opens 80/443 in the host firewall (Oracle's Ubuntu
   image blocks them even when the Security List allows them), creates
   `/opt/rag`, and schedules the weekday data refresh and the nightly backup.

### 3. The deploy key

The pipeline logs in as the `deploy` user with its own key:

```bash
# on your machine
ssh-keygen -t ed25519 -f rag-deploy -N "" -C github-actions-deploy
ssh-keyscan -t ed25519 <vm-ip> > known_hosts      # the server's host key
# on the VM
sudo mkdir -p /home/deploy/.ssh
sudo tee -a /home/deploy/.ssh/authorized_keys < rag-deploy.pub
sudo chown -R deploy:deploy /home/deploy/.ssh && sudo chmod 700 /home/deploy/.ssh && sudo chmod 600 /home/deploy/.ssh/authorized_keys
```

### 4. Production settings

On the VM, as `deploy`, create `/opt/rag/.env` from
[.env.production.example](../.env.production.example) and `chmod 600` it.
Fill in `DOMAIN`, `ACME_EMAIL`, `POSTGRES_PASSWORD`, `API_KEY`,
`GROQ_API_KEY` and `SEC_EDGAR_USER_AGENT`. Generate passwords and keys with:

```bash
openssl rand -base64 32 | tr -d '/+=' | cut -c1-32
```

### 5. GitHub

1. Settings → Environments → **New environment** `production`:
   - Secrets: `SSH_HOST` (the VM IP), `SSH_USER` (`deploy`),
     `SSH_PRIVATE_KEY` (contents of `rag-deploy`), `SSH_KNOWN_HOSTS`
     (contents of `known_hosts`).
   - Variables: `DOMAIN` (e.g. `yourname-rag.duckdns.org`).
   - Optional: restrict deployments to the `main` branch.
2. Actions → **Deploy** → Run workflow. Delete the local `rag-deploy` file
   once it is stored as a secret.
3. The first push creates the two packages on GHCR as **private**. Open each
   one (your profile → Packages → `rag-data-platform-backend` / `-frontend`)
   → Package settings → **Change visibility → Public**, so the server can pull
   without credentials. Then run the workflow again.

### 6. Load the data

```bash
cd /opt/rag
./deploy/compose.sh exec backend python -m app.cli seed      # ~10-15 minutes; real data only
./deploy/create-readonly-role.sh "$(openssl rand -base64 32 | tr -d '/+=' | cut -c1-32)"
# copy the printed password into QUERY_DATABASE_URL in .env, then:
./deploy/compose.sh up -d backend
```

### 7. Monitoring

Create a free [UptimeRobot](https://uptimerobot.com) HTTP monitor for
`https://<domain>/api/health` (5-minute interval, email alerts). Its public
status page is a good link to share.

## Day-to-day

Every command runs on the VM from `/opt/rag`.

| Task | Command |
|---|---|
| Deploy | Push to `main`; CI then Deploy run on their own. Or Actions → Deploy → Run workflow |
| Status | `./deploy/compose.sh ps` |
| Logs | `./deploy/compose.sh logs -f backend` (JSON; filter by `request_id`) |
| Roll back | `./deploy/deploy.sh rollback`, or `./deploy/deploy.sh sha-<commit>` for any earlier build |
| Rebuild schema index | `curl -X POST -H "X-API-Key: $(sed -n 's/^API_KEY=//p' .env)" http://127.0.0.1:8000/api/index-schema` |
| Refresh data now | `./deploy/compose.sh exec backend python -m app.cli refresh` |
| Backup now | `./deploy/backup.sh` |
| Restore | See the header of [deploy/backup.sh](../deploy/backup.sh) |
| Change a setting | Edit `.env`, then `./deploy/compose.sh up -d` |
| Rotate the Groq key / API key | Edit `.env`, then `./deploy/compose.sh up -d backend frontend` |

## Troubleshooting

- **Browser can't connect, but SSH works**: ports blocked. Check both the
  Security List ingress rules and `sudo iptables -L INPUT -n` (80/443 must be
  ACCEPTed before the REJECT rule).
- **Certificate errors**: DuckDNS must point at the VM IP *before* Caddy starts,
  and port 80 must be reachable for the ACME challenge.
  `./deploy/compose.sh logs caddy` shows the reason. Keep the `caddy_data`
  volume, or repeated re-issues hit Let's Encrypt rate limits.
- **"Rate limit" answers in the UI**: either the per-IP limit or Groq's
  free-tier quota. The Observability tab and the backend logs show which.
- **Backend unhealthy after deploy**: `deploy.sh` has already rolled back. Read
  `./deploy/compose.sh logs backend`; a failing migration or a missing `.env`
  value is the usual cause (production refuses to start without `API_KEY`).
- **Image pull denied**: the GHCR packages are still private (setup step 5.3).

## Rehearse locally

The same stack runs on any machine with Docker. Caddy issues a locally trusted
certificate for `localhost`:

```bash
docker compose build        # builds rag-data-platform-backend / -frontend:latest
IMAGE_PREFIX=rag-data-platform IMAGE_TAG=latest DOMAIN=localhost ACME_EMAIL=you@example.com \
  docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

Then check:
- `curl -k https://localhost/api/health` returns 200.
- `curl -k -X POST https://localhost/api/index-schema` returns 403.
- `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/docs` returns 404 (docs are off).
- `curl -I http://localhost` redirects to HTTPS (308).
