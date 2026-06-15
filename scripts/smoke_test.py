#!/usr/bin/env python3
"""Non-mutating GET smoke test of every API module. Internal QA only.
Reads ADMIN_TOKEN / PROVIDER_TOKEN from env. Hits localhost:8000.
"""
import os, json, urllib.request, collections

BASE = "http://localhost:8000"
ADMIN = os.environ.get("ADMIN_TOKEN", "")
PROV = os.environ.get("PROVIDER_TOKEN", "")


def call(path, token, method="GET"):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read(200)
    except urllib.error.HTTPError as e:
        return e.code, e.read(200)
    except Exception as e:
        return -1, str(e).encode()[:200]


def tag_of(path):
    # /api/v1/<module>/...
    parts = [p for p in path.split("/") if p]
    return parts[2] if len(parts) > 2 else path


def main():
    spec = json.load(urllib.request.urlopen(BASE + "/openapi.json", timeout=10))
    paths = spec["paths"]

    get_noparam = []
    get_param = 0
    for p, methods in paths.items():
        if "get" not in methods:
            continue
        if "{" in p:
            get_param += 1
            continue
        get_noparam.append(p)

    print(f"OpenAPI paths={len(paths)}  GET(no-param)={len(get_noparam)}  GET(with-param,skipped)={get_param}\n")

    by_tag = collections.defaultdict(lambda: collections.Counter())
    problems = []
    for p in sorted(get_noparam):
        st, body = call(p, ADMIN)
        by_tag[tag_of(p)][st] += 1
        # 200/204 ok; 401/403 auth; 422 needs params (works); others = investigate
        if st not in (200, 204, 401, 403, 422):
            problems.append((p, st, body.decode(errors="replace")[:160]))

    print("=== ADMIN results by module (status: count) ===")
    for tag in sorted(by_tag):
        c = by_tag[tag]
        print(f"  {tag:18s} " + "  ".join(f"{k}:{v}" for k, v in sorted(c.items())))

    print(f"\n=== NON-OK endpoints to investigate ({len(problems)}) ===")
    for p, st, b in problems:
        print(f"  [{st}] {p}  {b}")

    # Provider scoping spot-check: same endpoints provider portal uses
    print("\n=== PROVIDER token spot-check ===")
    for p in ["/api/v1/claims", "/api/v1/payments", "/api/v1/analytics/kpis",
              "/api/v1/portal/dashboard", "/api/v1/intake/entries", "/api/v1/denials"]:
        st, b = call(p, PROV)
        print(f"  [{st}] {p}  {b.decode(errors='replace')[:120]}")


if __name__ == "__main__":
    main()
