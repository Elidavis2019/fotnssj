scripts/benchmark.py

#!/usr/bin/env python3
# ════════════════════════════════════════════════════════════════════════
# Load test / benchmark tool.
# Simulates N concurrent students answering questions.
#
# Usage:
#   python scripts/benchmark.py --students 20 --duration 60
#   python scripts/benchmark.py --students 5  --duration 30 --host localhost:5000
# ════════════════════════════════════════════════════════════════════════
import sys
import os
import time
import random
import threading
import argparse
import urllib.request
import urllib.parse
import http.cookiejar
from dataclasses import dataclass, field
from typing import List


@dataclass
class StudentResult:
    student_id:  str
    requests:    int = 0
    successes:   int = 0
    errors:      int = 0
    latencies:   List[float] = field(default_factory=list)


def _make_session(host: str) -> urllib.request.OpenerDirector:
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def _get(opener, url: str) -> tuple:
    """Returns (status_code, body, latency_s)."""
    start = time.time()
    try:
        resp = opener.open(url, timeout=10)
        body = resp.read()
        return resp.status, body, time.time() - start
    except urllib.error.HTTPError as e:
        return e.code, b"", time.time() - start
    except Exception as e:
        return 0, b"", time.time() - start


def _post(opener, url: str, data: dict) -> tuple:
    start = time.time()
    try:
        payload  = urllib.parse.urlencode(data).encode()
        req      = urllib.request.Request(url, data=payload, method="POST")
        resp     = opener.open(req, timeout=10)
        body     = resp.read()
        return resp.status, body, time.time() - start
    except urllib.error.HTTPError as e:
        return e.code, b"", time.time() - start
    except Exception as e:
        return 0, b"", time.time() - start


def simulate_student(
    host: str,
    student_id: str,
    duration: float,
    result: StudentResult,
    stop_event: threading.Event,
):
    base    = f"http://{host}"
    opener  = _make_session(host)
    answers = ["4", "6", "5", "yes", "no", "3", "8", "2"]

    # Initial page load
    status, _, lat = _get(opener, f"{base}/student/{student_id}")
    result.requests  += 1
    result.latencies.append(lat)
    if status == 200:
        result.successes += 1
    else:
        result.errors += 1

    deadline = time.time() + duration

    while not stop_event.is_set() and time.time() < deadline:
        answer = random.choice(answers)
        status, _, lat = _post(opener, f"{base}/submit", {
            "answer":     answer,
            "start_time": str(time.time() - random.uniform(1, 15)),
        })
        result.requests  += 1
        result.latencies.append(lat)

        if status in (200, 302):
            result.successes += 1
        else:
            result.errors += 1

        # Simulate reading time
        time.sleep(random.uniform(0.5, 3.0))


def run_benchmark(host: str, n_students: int, duration: float):
    print(f"\n{'═'*60}")
    print(f"  FOTNSSJ Benchmark")
    print(f"  Host: {host} | Students: {n_students} | Duration: {duration}s")
    print(f"{'═'*60}\n")

    # Check server is up
    try:
        resp = urllib.request.urlopen(f"http://{host}/health", timeout=5)
        data = resp.read()
        print(f"Server health: {data.decode()[:100]}\n")
    except Exception as e:
        print(f"Server unreachable: {e}")
        sys.exit(1)

    results    = []
    threads    = []
    stop_event = threading.Event()
    start_time = time.time()

    for i in range(n_students):
        sid = f"bench_student_{i:03d}"
        r   = StudentResult(student_id=sid)
        results.append(r)
        t = threading.Thread(
            target=simulate_student,
            args=(host, sid, duration, r, stop_event),
            daemon=True,
        )
        threads.append(t)

    print(f"Starting {n_students} students...")
    for t in threads:
        t.start()
        time.sleep(0.05)   # Stagger start slightly

    # Progress reporting
    while time.time() - start_time < duration:
        elapsed = time.time() - start_time
        total_reqs = sum(r.requests for r in results)
        total_ok   = sum(r.successes for r in results)
        print(f"  [{elapsed:5.1f}s] requests={total_reqs} "
              f"success={total_ok} rps={total_reqs/max(elapsed,1):.1f}",
              end="\r")
        time.sleep(2)

    stop_event.set()
    for t in threads:
        t.join(timeout=5)

    # ── Results ───────────────────────────────────────────────────────
    total_time  = time.time() - start_time
    all_reqs    = sum(r.requests  for r in results)
    all_ok      = sum(r.successes for r in results)
    all_err     = sum(r.errors    for r in results)
    all_lats    = [l for r in results for l in r.latencies]

    all_lats.sort()
    p50  = all_lats[int(len(all_lats) * 0.50)] if all_lats else 0
    p95  = all_lats[int(len(all_lats) * 0.95)] if all_lats else 0
    p99  = all_lats[int(len(all_lats) * 0.99)] if all_lats else 0
    mean = sum(all_lats) / len(all_lats) if all_lats else 0

    print(f"\n\n{'═'*60}")
    print(f"  Results")
    print(f"{'═'*60}")
    print(f"  Duration:     {total_time:.1f}s")
    print(f"  Students:     {n_students}")
    print(f"  Total reqs:   {all_reqs}")
    print(f"  Successes:    {all_ok} ({100*all_ok/max(all_reqs,1):.1f}%)")
    print(f"  Errors:       {all_err}")
    print(f"  Req/s:        {all_reqs/total_time:.2f}")
    print(f"  Latency mean: {mean*1000:.0f}ms")
    print(f"  Latency p50:  {p50*1000:.0f}ms")
    print(f"  Latency p95:  {p95*1000:.0f}ms")
    print(f"  Latency p99:  {p99*1000:.0f}ms")
    print(f"{'═'*60}\n")

    # Per-student summary
    print("  Per-student breakdown:")
    for r in sorted(results, key=lambda x: x.errors, reverse=True)[:5]:
        lats = sorted(r.latencies)
        p50s = lats[len(lats)//2] if lats else 0
        print(f"    {r.student_id}: reqs={r.requests} "
              f"ok={r.successes} err={r.errors} p50={p50s*1000:.0f}ms")

    return all_ok / max(all_reqs, 1) >= 0.95


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host",     default="localhost:5000")
    parser.add_argument("--students", type=int, default=10)
    parser.add_argument("--duration", type=float, default=30.0)
    args = parser.parse_args()

    ok = run_benchmark(args.host, args.students, args.duration)
    sys.exit(0 if ok else 1)