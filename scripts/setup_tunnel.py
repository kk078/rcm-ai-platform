#!/usr/bin/env python3
"""
Cloudflare Tunnel setup for Aethera AI.
Creates the tunnel, configures ingress, creates DNS CNAME, writes TUNNEL_TOKEN to .env.
"""
import json, base64, secrets, re, sys, os

try:
    import httpx
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "httpx",
                    "--break-system-packages", "-q"], check=True)
    import httpx

# ── Read .env ─────────────────────────────────────────────────────────────────
ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")

env_vars = {}
with open(ENV_PATH) as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            val = val.split("#")[0].strip()
            env_vars[key.strip()] = val

TOKEN      = env_vars.get("CLOUDFLARE_API_TOKEN", "").strip()
ACCOUNT_ID = env_vars.get("CLOUDFLARE_ACCOUNT_ID", "").strip()

if not TOKEN:
    sys.exit("ERROR: CLOUDFLARE_API_TOKEN is empty in .env — add it and retry.")

HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
client  = httpx.Client(timeout=30)

def cf(method, path, **kwargs):
    url  = f"https://api.cloudflare.com/client/v4{path}"
    resp = client.request(method, url, headers=HEADERS, **kwargs)
    data = resp.json()
    if not data.get("success"):
        sys.exit(f"ERROR calling {method} {path}:\n{json.dumps(data, indent=2)}")
    return data["result"]

# ── 1. Zone ID ────────────────────────────────────────────────────────────────
print("1. Looking up zone for aetherahealthcare.com ...")
zones = cf("GET", "/zones", params={"name": "aetherahealthcare.com"})
if not zones:
    sys.exit("ERROR: Zone 'aetherahealthcare.com' not found in this account.")
zone_id = zones[0]["id"]
print(f"   Zone ID: {zone_id}")

# ── 2. Create tunnel ──────────────────────────────────────────────────────────
print("\n2. Creating tunnel 'aethera-production' ...")
tunnel_secret = base64.b64encode(secrets.token_bytes(32)).decode()
result = cf("POST", f"/accounts/{ACCOUNT_ID}/cfd_tunnel", json={
    "name": "aethera-production",
    "config_src": "cloudflare",
    "tunnel_secret": tunnel_secret,
})
tunnel_id    = result["id"]
tunnel_token = result["token"]
print(f"   Tunnel ID: {tunnel_id}")

# ── 3. Ingress rules ──────────────────────────────────────────────────────────
print("\n3. Configuring ingress: rcm.aetherahealthcare.com → http://nginx:80 ...")
cf("PUT", f"/accounts/{ACCOUNT_ID}/cfd_tunnel/{tunnel_id}/configurations", json={
    "config": {
        "ingress": [
            {"hostname": "rcm.aetherahealthcare.com", "service": "http://nginx:80"},
            {"service": "http_status:404"},
        ]
    }
})
print("   Ingress configured.")

# ── 4. DNS CNAME ──────────────────────────────────────────────────────────────
print(f"\n4. Creating CNAME: rcm → {tunnel_id}.cfargotunnel.com ...")
try:
    cf("POST", f"/zones/{zone_id}/dns_records", json={
        "type":    "CNAME",
        "name":    "rcm",
        "content": f"{tunnel_id}.cfargotunnel.com",
        "proxied": True,
        "ttl":     1,
    })
    print("   DNS record created.")
except SystemExit as e:
    if "already exists" in str(e):
        print("   DNS record already exists — skipping.")
    else:
        raise

# ── 5. Write TUNNEL_TOKEN to .env ─────────────────────────────────────────────
print("\n5. Writing TUNNEL_TOKEN to .env ...")
with open(ENV_PATH) as f:
    content = f.read()

content = re.sub(
    r"^TUNNEL_TOKEN=.*$",
    f"TUNNEL_TOKEN={tunnel_token}",
    content,
    flags=re.MULTILINE,
)
with open(ENV_PATH, "w") as f:
    f.write(content)
print("   .env updated.")

# ── Done ──────────────────────────────────────────────────────────────────────
print(f"""
✓ Tunnel setup complete!
  Name:  aethera-production
  ID:    {tunnel_id}
  DNS:   rcm.aetherahealthcare.com → {tunnel_id}.cfargotunnel.com

Next step: start the cloudflared container.
""")
