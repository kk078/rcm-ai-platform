# Local push-to-deploy, executed by a self-hosted GitHub Actions runner ON the host
# that runs the Aethera Podman stack. Triggered by deploy.yml after tests pass on main.
# CI-safe version of run-all-deploys.bat (no `pause`, fails loudly on error).
$ErrorActionPreference = 'Stop'
$Repo = 'D:\rcm-ai-platform'

Write-Host '== Aethera push-to-deploy =='
Set-Location $Repo

# 1. Pull the just-pushed commit into the live working copy (src/ is bind-mounted into api/celery).
git pull --ff-only

# 2. API + Celery hot-read the mounted ./src, so a restart picks up code changes.
#    (Container names follow the `aethera-ai-*` prefix used in run-all-deploys.bat.)
podman restart aethera-ai-api-1
foreach ($c in 'aethera-ai-celery-worker-1','aethera-ai-celery-beat-1') {
  if (podman ps -a --format '{{.Names}}' | Select-String -SimpleMatch $c) { podman restart $c }
}

# 3. Reload nginx (serves the built portal dist via bind mount).
podman exec aethera-ai-nginx-1 nginx -s reload 2>$null
if ($LASTEXITCODE -ne 0) { podman restart aethera-ai-nginx-1 }

Write-Host 'Deployed: pulled latest + restarted api/celery + reloaded nginx.'

# NOTE — not automated here yet (need validation before enabling):
#  * Staff/Provider portal UI rebuild must run in the Linux sandbox (linux-x64 esbuild),
#    then the new dist is bind-mounted into nginx. Wire this once confirmed.
#  * The AIAgents image is baked: `podman cp` + `podman commit` + `podman restart` on change.
