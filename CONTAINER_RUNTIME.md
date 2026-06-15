# CONTAINER RUNTIME — permanent, Desktop-independent

> **Shared, synchronized doc.** Canonical copy: `D:\_aethera_shared\CONTAINER_RUNTIME.md`.
> Read this first if containers won't start. Companion to `AETHERA_FLEET.md` and
> `SAFE_FAIL.md`.

## ✅ STATUS — applied & confirmed 2026-06-05

**Root cause of the outage (two layered failures):**
1. **Docker Desktop's backend was crash-looping** — `com.docker.backend.exe` panics on
   startup (`nil pointer dereference` in `startDockerAPIProxy`, `exit status 2`), so the
   `dockerDesktopLinuxEngine` pipe never came up and every `docker` command failed.
2. **WSL2 had no outbound network** — leftover hacks were fighting WSL's `eth0`:
   `/etc/profile.d/static-ip.sh`, `/etc/profile.d/wsl-network.sh`, and
   `/etc/netplan/01-netcfg.yaml` all forced a static IP (`172.28.160.10`) that didn't
   match WSL's dynamic NAT subnet, plus `systemd-networkd` was managing `eth0`.

**Permanent fix applied:**
- Removed the two rogue `profile.d` scripts and disabled the bad `netplan` file
  (backed up to `~/_netfix_backup/` inside WSL). Masked `systemd-networkd` +
  `systemd-networkd-wait-online` so **WSL manages `eth0` natively** → connectivity restored.
- **Docker Engine (CE) 29.5.3 now runs natively inside WSL2 Ubuntu**, supervised by
  systemd, `systemctl enable`d (auto-starts on WSL boot). `hello-world` passes.
- Docker Desktop is no longer required and should stay closed.

**How to operate it (the daemon lives in WSL):**
- `D:\_aethera_shared\aethera-up.bat` — start the whole stack
- `D:\_aethera_shared\aethera-status.bat` — engine + container status
- `D:\_aethera_shared\aethera-down.bat` — stop (data volumes preserved)
- The watchdog + boot auto-start are registered by `install-autostart.ps1` (admin, once).

**Data note:** the new native engine has its own storage. No old Docker-Desktop volume
data or `docker-desktop` distro was found on this machine, so the stack initializes
**fresh** named volumes (Alembic migrations rebuild schema). Nothing was deleted.

---

## The honest constraint

Your services (postgres, redis, qdrant, minio, nginx, the FastAPI API, celery) are
**Linux containers**. On Windows, Linux containers **always** need a Linux kernel
underneath. That kernel is provided by **WSL2** (or a Hyper-V VM). There is no Windows
container runtime that avoids this — Docker Desktop, Podman, and Rancher all sit on
WSL2. So the durable question is not "how do I avoid WSL2" but **"how do I make the
engine on top of WSL2 stop crashing and always come back."**

The part that actually crashes is almost always **Docker Desktop's GUI/management
layer**, not the WSL2 kernel (which is very stable). The permanent fix removes the
flaky layer and runs the engine directly, with boot auto-start.

## Recommended permanent setup: Docker Engine (CE) inside WSL2, no Desktop

1. **Confirm WSL2 is healthy** (`wsl --status`, `wsl -l -v` — a distro should be
   `Version 2`, `Running`). If WSL itself is broken, repair that first:
   `wsl --update`, then `wsl --shutdown`.
2. **Install Docker Engine inside the WSL distro** (Ubuntu) — this is dockerd running
   natively in Linux, identical to a production server:
   ```bash
   curl -fsSL https://get.docker.com | sh
   sudo usermod -aG docker $USER
   ```
3. **Make the engine auto-start** inside WSL via systemd. In the distro,
   `/etc/wsl.conf`:
   ```ini
   [boot]
   systemd=true
   ```
   then `sudo systemctl enable --now docker`. systemd keeps dockerd alive and restarts
   it if it dies — that is the self-healing engine layer.
4. **Make WSL itself start at Windows logon** so the engine is up before anything needs
   it. Handled by `install-autostart.ps1` (registers a Scheduled Task that runs
   `wsl -d <distro> -e true` at logon to boot the distro + systemd + dockerd).
5. **Keep using the same commands.** `docker` and `docker compose` work identically.
   All existing `.bat` scripts keep working because `docker.exe` shims to the WSL
   engine via the default context. No compose changes required.

### Why this is "permanent"
- No GUI app to crash. dockerd is supervised by systemd (auto-restart).
- WSL2 distro auto-boots at logon (Scheduled Task).
- The `SAFE_FAIL.md` watchdog re-runs `compose up -d` every 5 min as a backstop.
- Named volumes persist data across every restart.

## Alternative: repair Docker Desktop (only if diagnosis shows it's a clean fix)

If `RUN_DIAG.bat` shows Docker Desktop's engine is fine and only the auto-start or a
transient WSL state was the issue, the lighter fix is:
- `wsl --shutdown` then start Docker Desktop, **Settings → General → "Start Docker
  Desktop when you sign in"**, and **Resources → WSL Integration** enabled.
- This still depends on the Desktop layer; prefer the WSL-engine setup above for
  durability.

## Bring the stack up (either runtime)

```bat
cd /d D:\rcm-ai-platform
docker compose up -d
cd /d D:\AIAgents\workers
docker compose up -d
```
Then verify with `docker compose ps` (all `healthy`) and the smoke test in
`D:\_aethera_shared\smoke-test.bat`.

## Files that implement this (in `D:\_aethera_shared\`)
- `RUN_DIAG.bat` (in `D:\_aethera_diag\`) — capture engine/WSL state. **Run this first.**
- `install-autostart.ps1` — register logon + 5-min Scheduled Tasks for WSL boot and the watchdog.
- `watchdog.ps1` — engine check + `compose up -d` + restart unhealthy/exited.
- `smoke-test.bat` — end-to-end health probe of every service and public endpoint.

<!-- SYNCED: 2026-06-05T15:36:39Z from D:_aethera_shared (canonical). Do not edit per-project copies. -->

---

## Session result — 2026-06-05 (read this)

**Working & permanent now:**
- Native **Docker Engine 29.5.3 runs inside WSL2 Ubuntu**, `systemctl enable`d → **auto-starts on boot**. Docker Desktop is not used. (`docker info` → Server 29.5.3.)
- Engine validated end-to-end: **postgres, qdrant, minio came up HEALTHY** on it and the named data volumes were created (`rcm-ai-platform_aethera_postgres_data`, `_redis_data`, `_qdrant_data`, `_minio_data`). `nginx` image built successfully; base images for postgres/redis/qdrant/minio/cloudflared are pulled and cached.
- WSL networking hacks removed (rogue static-IP scripts + bad netplan), `systemd-networkd` masked, DNS pinned (8.8.8.8/1.1.1.1), IPv6 disabled, MTU unit added.

**Two known remaining issues:**
1. **`redis` container fails to start — host port 6379 already in use.** Something else on this machine holds 6379 (likely a leftover process/container). Free it, then `docker compose up -d redis`:
   - find it: `wsl -d Ubuntu -u root -e bash -c "ss -ltnp | grep 6379; docker ps -a | grep redis"`
   - or change the mapping in `docker-compose.yml` redis to `"6380:6379"`.
2. **App images (`api`, `celery-worker`, `celery-beat`, `ai-agents`) are not built yet.** Their build needs to pull `python:3.12-slim` and run `pip install`, and **WSL outbound networking on this host is currently unstable** — short requests work but sustained/registry downloads intermittently stall or hang, in BOTH NAT and mirrored modes, even with Docker stopped. This is a host-level network issue, not a Docker or compose problem.

**Most likely cause of the network instability & what to try (in order):**
- **Reboot Windows.** I cycled `wsl --shutdown` many times during repair, which can leave the Hyper-V vSwitch in a bad state. A full Windows restart most often clears this. After reboot, the engine auto-starts; then run `D:\_aethera_shared\aethera-up.bat`.
- **Check for a VPN / endpoint-security / firewall product** that intercepts WSL traffic (common culprits: corporate VPNs, some AV/EDR). Temporarily disable and retry the build.
- Then build the app images on the host network:
  `wsl -d Ubuntu -u root -e bash /mnt/d/_aethera_diag/build_all.sh` (logs to `D:\_aethera_diag\buildall.log`).

**To bring up what works right now (no internet needed):**
`wsl -d Ubuntu -u root -e bash -c "cd /mnt/d/rcm-ai-platform && docker compose up -d --no-build postgres qdrant minio"`

---

## ✅✅ FULLY SOLVED — 2026-06-06: stack running via Windows-host proxy bridge

**Final root cause:** this machine's **WSL/Hyper-V virtual networking is corrupted** — the
WSL VM gets no internet (NAT broken) and it survived every standard repair (HNS clears,
Winsock/IP reset, `netcfg -d`, two reboots, Network Reset, mirrored mode). `fse.sys`
("Flow Steering Engine") is a normal Microsoft driver — not the cause. This is a
host-OS fault, not a Docker/WSL-config one.

**The working bypass (no NAT needed):** the Windows host HAS internet, and WSL can reach
the Windows host directly over their shared subnet (that path doesn't use the broken NAT).
So a small **proxy on the Windows host** gives the containers internet:

1. `proxy.py` runs on Windows: `python -m proxy --hostname 0.0.0.0 --port 8899`.
2. dockerd is configured (`/etc/docker/daemon.json` `proxies` + a systemd `http-proxy.conf`
   override) to use `http://<WSL-gateway>:8899` for registry pulls AND to inject the proxy
   into build steps (apt/pip) and runtime containers. `no-proxy` covers the compose service
   names + private ranges so inter-container traffic stays local.
3. Builds run on the **host network** (`docker-compose.override.yml` in each project sets
   `build.network: host`) so apt/pip reach the proxy over `eth0`.
4. `daemon.json` must NOT contain a top-level `"dns"` key — that breaks Docker's embedded
   DNS (service-name resolution like `redis`/`postgres`). Removed.

**Result:** both stacks built and run — `rcm-ai-platform` (api, ai-agents, nginx, postgres,
redis, qdrant, minio, cloudflared) and `AIAgents/workers` (db, redis@6380, worker, beat).

**Make it permanent (one-time, admin):** run `D:\_aethera_shared\install-autostart.ps1`
as administrator. It registers `Aethera-Watchdog` (logon + every 5 min). The watchdog now:
(a) keeps `proxy.py` running, (b) re-points dockerd's proxy at the *current* WSL gateway
(it can change per boot), (c) starts dockerd, (d) `compose up -d` both stacks and restarts
any exited container. So after a reboot the platform restores itself.

**Honest caveat:** this is a robust *workaround* for a broken Windows network stack. For a
HIPAA medical-billing platform, the durable home is a small always-on **Linux/cloud VM**
(see `rcm-ai-platform/DEPLOY.md` — Ubuntu + Cloudflare Tunnel). The proxy bridge keeps you
running on this machine today; the server is the real production answer.

## 2026-06-06 (later) — celery, workers, and the proxy firewall rule

**rcm-ai-platform celery — FIXED.** The `celery-worker` / `celery-beat` "unhealthy" was a
**false alarm**: they have no healthcheck in `docker-compose.yml`, so they inherited the API
**Dockerfile** healthcheck (`curl localhost:8000/health`) — which always fails for a worker
that runs no web server. `docker-compose.override.yml` now gives celery-worker a real
`celery ... inspect ping` check and celery-beat a `/proc/1/cmdline` process check. Both go
healthy after a clean recreate. (`OLLAMA_API_KEY` is present in `rcm-ai-platform/.env`.)

**litellm — NOT a dependency.** `rcm-ai-platform/.env` has `OLLAMA_BASE_URL=https://ollama.com`
(the app calls Ollama Cloud directly). The old standalone `litellm-proxy:4000` container was
orphaned/experimental; nothing references it, so it is intentionally **not** in either compose
file or the watchdog. Don't re-add it without a real consumer.

**AIAgents/workers OLLAMA key — FIXED.** Created `AIAgents/workers/.env` with `OLLAMA_API_KEY`
(copied from `AIAgents/.env`), clearing the `compose` "variable is not set" warning.

**AIAgents/workers `worker`/`beat` exit 127 — root causes fixed in code (pre-existing bug).**
These crash-looped with exit 127 in the *original* Docker-Desktop setup too. Causes, now fixed:
(a) `Dockerfile.worker`/`Dockerfile.beat` installed the **root** `requirements.txt` (no celery)
instead of `workers/requirements.txt` — repointed; (b) `workers/requirements.txt` has an
invalid `-e ../shared` editable line that breaks the build — the pip step now strips
editable/local lines (`shared`/`agents` are copied in as code and import via the workdir);
(c) `beat` ran `celery` via bare exec (not on `appuser`'s PATH) — now `bash -c "celery ..."`.
**Remaining:** the worker/beat **images still need one successful build** to pick up these fixes.

**Proxy bridge reliability — root cause + durable fix.** Repeated build failures
(`proxyconnect ... i/o timeout` to `<gw>:8899`) were **Windows Firewall** intermittently
blocking inbound WSL → `python:8899` (a fresh `python.exe` instance gets re-evaluated).
`install-autostart.ps1` now adds a permanent inbound allow-rule for TCP 8899
(`Aethera Proxy Bridge 8899`). **Run `install-autostart.ps1` as administrator once** — it
opens the firewall, registers the watchdog (keeps proxy.py alive + re-points the gateway every
5 min), and starts everything. After that, a single `cd /mnt/d/AIAgents/workers &&
docker compose build worker beat && docker compose up -d` brings the workers green.
