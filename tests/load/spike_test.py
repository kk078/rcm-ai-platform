#!/usr/bin/env python3
"""
Aethera AI — Spike + Load Test Suite
Uses httpx for async HTTP calls; no external tool required.

Run:
    python tests/load/spike_test.py --base-url http://localhost:8000 --token <jwt>
    python tests/load/spike_test.py --base-url https://rcm.aetherahealthcare.com/api/v1 --token <jwt>

Scenarios:
  - spike:    sudden burst of 50 concurrent users for 30s
  - ramp:     gradual ramp from 1→50 users over 60s
  - soak:     constant 10 users for 5 minutes
  - canary:   compare latency between two endpoints

Results: printed as a table + saved to tests/load/results/<timestamp>.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from datetime import datetime
from pathlib import Path

import httpx


# ── Test endpoints ────────────────────────────────────────────────────────────

ENDPOINTS = {
    "health":          ("GET",  "/health",              None),
    "ready":           ("GET",  "/ready",               None),
    "dashboard":       ("GET",  "/api/v1/queues/dashboard", None),
    "billing":         ("GET",  "/api/v1/billing/revenue/dashboard", None),
    "claims_list":     ("GET",  "/api/v1/claims/",      None),
    "ai_chat":         ("POST", "/api/v1/ai/chat",      {
        "messages": [{"role": "user", "content": "What is CPT code 99213?"}],
        "stream": False,
    }),
}


# ── Core runner ───────────────────────────────────────────────────────────────

async def single_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    payload: dict | None,
) -> dict:
    start = time.perf_counter()
    status = 0
    error = None
    try:
        if method == "GET":
            resp = await client.get(url)
        else:
            resp = await client.post(url, json=payload)
        status = resp.status_code
    except Exception as e:
        error = str(e)
    latency = (time.perf_counter() - start) * 1000  # ms
    return {"status": status, "latency_ms": latency, "error": error}


async def run_scenario(
    base_url: str,
    token: str,
    endpoint_name: str,
    concurrency: int,
    duration_s: int,
    ramp_seconds: int = 0,
) -> dict:
    method, path, payload = ENDPOINTS[endpoint_name]
    url = base_url.rstrip("/") + path
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    results = []
    start_wall = time.time()

    async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
        async def worker(delay: float = 0.0):
            if delay:
                await asyncio.sleep(delay)
            while time.time() - start_wall < duration_s:
                r = await single_request(client, method, url, payload)
                results.append(r)
                await asyncio.sleep(0.05)  # ~20 RPS per worker at rest

        if ramp_seconds:
            # Ramp up workers gradually
            tasks = []
            for i in range(concurrency):
                delay = (i / concurrency) * ramp_seconds
                tasks.append(asyncio.create_task(worker(delay)))
            await asyncio.gather(*tasks)
        else:
            await asyncio.gather(*[worker() for _ in range(concurrency)])

    return _analyze(results, endpoint_name, concurrency, duration_s)


def _analyze(results: list[dict], name: str, concurrency: int, duration_s: int) -> dict:
    total = len(results)
    if not total:
        return {"endpoint": name, "total_requests": 0}

    ok = [r for r in results if r["status"] == 200]
    errors = [r for r in results if r["error"] or (r["status"] not in (200, 201, 204))]
    latencies = [r["latency_ms"] for r in ok]

    return {
        "endpoint": name,
        "concurrency": concurrency,
        "duration_s": duration_s,
        "total_requests": total,
        "success_rate_pct": round(len(ok) / total * 100, 1),
        "error_count": len(errors),
        "rps": round(total / duration_s, 1),
        "latency_p50_ms": round(statistics.median(latencies), 1) if latencies else 0,
        "latency_p95_ms": round(sorted(latencies)[int(len(latencies) * 0.95)], 1) if latencies else 0,
        "latency_p99_ms": round(sorted(latencies)[int(len(latencies) * 0.99)], 1) if latencies else 0,
        "latency_max_ms": round(max(latencies), 1) if latencies else 0,
        "latency_mean_ms": round(statistics.mean(latencies), 1) if latencies else 0,
        "error_samples": [r["error"] or f"HTTP {r['status']}" for r in errors[:3]],
    }


def print_results(results: list[dict]):
    print("\n" + "=" * 80)
    print(f"{'AETHERA AI — LOAD TEST RESULTS':^80}")
    print("=" * 80)
    headers = ["Endpoint", "RPS", "Success%", "p50ms", "p95ms", "p99ms", "Errors"]
    col_w = [22, 7, 9, 7, 7, 7, 7]
    header_row = "".join(h.ljust(w) for h, w in zip(headers, col_w))
    print(header_row)
    print("-" * 80)
    for r in results:
        row = [
            r["endpoint"][:20],
            str(r.get("rps", 0)),
            f"{r.get('success_rate_pct', 0)}%",
            str(r.get("latency_p50_ms", 0)),
            str(r.get("latency_p95_ms", 0)),
            str(r.get("latency_p99_ms", 0)),
            str(r.get("error_count", 0)),
        ]
        print("".join(str(v).ljust(w) for v, w in zip(row, col_w)))
    print("=" * 80)


async def main():
    parser = argparse.ArgumentParser(description="Aethera AI Spike/Load Tester")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--token", required=True, help="JWT access token")
    parser.add_argument(
        "--scenario",
        choices=["spike", "ramp", "soak", "quick"],
        default="quick",
    )
    parser.add_argument("--endpoint", default="health", choices=list(ENDPOINTS))
    args = parser.parse_args()

    print(f"\nAethera AI Load Tester — scenario={args.scenario} target={args.base_url}")
    all_results = []

    if args.scenario == "quick":
        # Quick smoke: 5 users, 10s, health + dashboard
        for ep in ["health", "ready", "dashboard"]:
            print(f"  Running quick test: {ep}...")
            r = await run_scenario(args.base_url, args.token, ep, 5, 10)
            all_results.append(r)

    elif args.scenario == "spike":
        # Spike: sudden 50 users for 30s
        print(f"  Spike test: 50 users × 30s on {args.endpoint}...")
        r = await run_scenario(args.base_url, args.token, args.endpoint, 50, 30)
        all_results.append(r)

    elif args.scenario == "ramp":
        # Ramp: gradual 1→20 users over 60s
        print(f"  Ramp test: 1→20 users over 60s on {args.endpoint}...")
        r = await run_scenario(args.base_url, args.token, args.endpoint, 20, 60, ramp_seconds=30)
        all_results.append(r)

    elif args.scenario == "soak":
        # Soak: 10 users for 5 minutes
        print(f"  Soak test: 10 users × 300s on {args.endpoint}...")
        r = await run_scenario(args.base_url, args.token, args.endpoint, 10, 300)
        all_results.append(r)

    print_results(all_results)

    # Save results
    out_dir = Path("tests/load/results")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"{args.scenario}_{ts}.json"
    out_file.write_text(json.dumps(all_results, indent=2))
    print(f"\nResults saved → {out_file}")


if __name__ == "__main__":
    asyncio.run(main())
