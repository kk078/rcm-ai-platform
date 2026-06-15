# SAFE-FAIL & SELF-HEALING RUNBOOK

> **Shared, synchronized doc.** Canonical copy: `D:\_aethera_shared\SAFE_FAIL.md`.
> Edit the canonical copy, then run `sync-docs.bat`. Companion to `AETHERA_FLEET.md`
> and `CONTAINER_RUNTIME.md`.

Goal: when something breaks, the system **recovers itself** and, where it can't,
**fails loudly but partially** instead of taking the whole platform down.

---

## 1. The three layers of safe-fail

| Layer | Mechanism | Status |
|---|---|---|
| **Container** | `restart:` policy + `healthcheck` per service | Present in both compose files ✓ |
| **Engine** | Docker engine auto-starts on boot + comes back after crash | Added — see `CONTAINER_RUNTIME.md` |
| **Stack** | A watchdog restarts unhealthy/exited containers on a schedule | Added — `watchdog.ps1` |

---

## 2. Container layer — what's already correct, what to fix

Both `rcm-ai-platform/docker-compose.yml` and `AIAgents/workers/docker-compose.yml`
already set `restart: unless-stopped` / `restart: always` and define healthchecks.
Keep it that way. Rules:

- **Every long-running service** must have `restart: unless-stopped` (preferred over
  `always`, so a deliberate `docker compose stop` stays stopped).
- **Every service** that something depends on must have a real `healthcheck` and be
  referenced with `depends_on: { condition: service_healthy }`.
- **Never** silence a crash with `restart: always` alone. A container that exits
  127 / 1 immediately will crash-loop forever and `restart` just hides it. Find the
  root cause (see §4).

### Known issues to fix at the container layer (from `container_status.txt`)
1. **`workers-worker-1` exited 127 (crash loop).** Exit 127 = "command not found".
   The command is `bash -c "... celery -A workers.celery_app.app worker ..."`. Either
   `bash` isn't in the image, or the `workers.celery_app` module path is wrong inside
   the container. Fix in `AIAgents/workers/Dockerfile.worker` / the `command:` — do
   not paper over it with restart.
2. **`AIAgents workers-beat-1` stuck "Created"** and **`rcm-ai-platform-ai-agents-1`
   stuck "Created"** — they never started. Usually a failed build or an unmet
   `depends_on` health condition. Rebuild with `--build` and read the build log.
3. **`aethera-worker` / `aethera-frontend` reported "unhealthy"** — the container is
   up but its healthcheck fails. Check the healthcheck command and the app logs.

---

## 3. Stack layer — the watchdog

`D:\_aethera_shared\watchdog.ps1` is a self-contained, dependency-free PowerShell
watchdog. Every run it:

1. Verifies the Docker engine answers (`docker info`). If not, it tries to start it
   (see `CONTAINER_RUNTIME.md`) and logs the attempt.
2. For each Compose project, runs `docker compose up -d` (idempotent — only starts
   what's down) and then restarts any container reporting `exited` or `unhealthy`.
3. Appends a timestamped line to `D:\_aethera_diag\watchdog.log`.

It is registered as a **Scheduled Task** that runs at logon and every 5 minutes, so
the platform heals without anyone watching. Registration is done by
`install-autostart.ps1` (see `CONTAINER_RUNTIME.md`).

**Manual run any time:**
```
powershell -ExecutionPolicy Bypass -File D:\_aethera_shared\watchdog.ps1
```

---

## 4. Diagnosing a crash-looping or unhealthy container

```
docker compose ps                          # which service, what state
docker compose logs --tail=120 <service>   # why it died
docker inspect --format "{{json .State.Health}}" <container>   # healthcheck output
```
- Exit 127 → command/binary missing in image → fix Dockerfile/command.
- Exit 1 fast → app config/env error → check `.env` and logs.
- "unhealthy" but running → healthcheck wrong or dependency slow → widen
  `start_period`, fix the test command, or fix the dependency.

---

## 5. Port hygiene (prevents silent "won't start")

Both Compose stacks publish **redis on host 6379**; only one can bind it. If you need
both stacks at once, edit one mapping, e.g. in `AIAgents/workers/docker-compose.yml`:
```yaml
  redis:
    ports:
      - "6380:6379"   # was 6379:6379
```
Other already-claimed host ports on this machine: 5432 (postgres), 8000 (api),
8080 (frontend), 8088 (nginx), 9000/9001 (minio), 6333 (qdrant), 4000 (litellm).

---

## 6. Graceful degradation rules

- **Serverless stays up regardless.** `crm.`, `os.` (static), apex, `ai.`, `agents.`
  are Cloudflare-hosted and do not depend on this machine. Never route their critical
  paths through the local Docker API.
- **Tunnel-backed `rcm.`/`admin.`** depend on local Docker. The watchdog keeps them
  alive; if the engine is truly down, they should return Cloudflare's error page, not
  hang. That is acceptable partial failure.
- **Data safety first.** Postgres/Redis/Qdrant/MinIO use **named volumes** — restarts
  and rebuilds never wipe data. Never `docker compose down -v` on this machine without
  an explicit, confirmed backup (`-v` deletes volumes = data loss).

<!-- SYNCED: 2026-06-05T15:36:39Z from D:_aethera_shared (canonical). Do not edit per-project copies. -->
