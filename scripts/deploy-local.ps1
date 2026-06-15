# Local push-to-deploy, executed by a self-hosted GitHub Actions runner ON the host
# that runs the Aethera Podman stack. Triggered by deploy.yml after tests pass on main.
$ErrorActionPreference = 'Stop'
$Repo = 'D:\rcm-ai-platform'

Write-Host '== Aethera push-to-deploy =='
Set-Location $Repo

# 1. Pull the just-pushed commit into the live working copy (src/ is bind-mounted into api/celery).
#    -c safe.directory avoids git's "dubious ownership" error if the runner account != repo owner.
git -c safe.directory='D:/rcm-ai-platform' pull --ff-only

# 2. Restart only the containers that actually exist (compose project prefix: rcm-ai-platform-*).
$running = (podman ps -a --format '{{.Names}}')
function Restart-IfPresent($name) {
  if ($running -contains $name) {
    Write-Host "restarting $name"
    podman restart $name | Out-Null
  } else {
    Write-Host "skip (not present): $name"
  }
}
# api + celery hot-read the mounted ./src, so a restart picks up the new code.
Restart-IfPresent 'rcm-ai-platform-api-1'
Restart-IfPresent 'rcm-ai-platform-celery-worker-1'
Restart-IfPresent 'rcm-ai-platform-celery-beat-1'

# 3. Reload nginx (serves the built portal dist via bind mount); restart if reload fails.
if ($running -contains 'rcm-ai-platform-nginx-1') {
  podman exec rcm-ai-platform-nginx-1 nginx -s reload 2>$null
  if ($LASTEXITCODE -ne 0) { podman restart rcm-ai-platform-nginx-1 | Out-Null }
}

Write-Host 'Deployed: pulled latest + restarted api/celery + reloaded nginx.'

# NOTE — not automated here yet (need validation before enabling):
#  * Staff/Provider portal UI rebuild must run in the Linux sandbox (linux-x64 esbuild),
#    then the new dist is bind-mounted into nginx.
#  * The AIAgents image (rcm-ai-platform-ai-agents-1) is baked: podman cp + commit + restart on change.
