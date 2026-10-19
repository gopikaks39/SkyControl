"""Small concurrent load test against a running SkyControl server; reports measured latencies only.

    python scripts/load_test.py --base http://127.0.0.1:5000 --user supervisor --password <pw> --workers 8 --rounds 25
"""
import argparse
import json
import statistics
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor


def call(base, path, token=None, payload=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(base + path, data=json.dumps(payload).encode() if payload is not None else None,
                                 headers=headers, method='POST' if payload is not None else 'GET')
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
            return r.status, (time.perf_counter() - start) * 1000, body
    except urllib.error.HTTPError as e:
        return e.code, (time.perf_counter() - start) * 1000, b''
    except Exception:
        return 0, (time.perf_counter() - start) * 1000, b''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://127.0.0.1:5000')
    ap.add_argument('--user', default='supervisor')
    ap.add_argument('--password', required=True)
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--rounds', type=int, default=25)
    args = ap.parse_args()
    status, _, body = call(args.base, '/api/auth/login', payload={'username': args.user, 'password': args.password})
    if status != 200:
        raise SystemExit(f'login failed ({status})')
    token = json.loads(body)['token']
    endpoints = {
        'health': ('/api/health', None), 'dashboard': ('/api/dashboard', None), 'flights': ('/api/flights', None),
        'airspace frame': ('/api/airspace/frame?offset=2400', None), 'gaps': ('/api/gaps', None),
        'scenario create': ('/api/lab/runs', {'scenario': 'collision'}),
        'readback verify': ('/api/comms/verify', {'clearance': {'callsign': 'BAW425', 'level': 12000}, 'readback': 'climb FL120 speedbird 425'}),
    }
    print(f'{args.workers} workers x {args.rounds} rounds per endpoint against {args.base}')
    print(f"{'endpoint':18s} {'ok':>5s} {'p50 ms':>8s} {'p95 ms':>8s} {'max ms':>8s}")
    for name, (path, payload) in endpoints.items():
        with ThreadPoolExecutor(args.workers) as pool:
            results = list(pool.map(lambda _: call(args.base, path, token, payload), range(args.workers * args.rounds)))
        times = sorted(r[1] for r in results)
        ok = sum(1 for r in results if 200 <= r[0] < 300)
        p95 = times[int(0.95 * (len(times) - 1))]
        print(f'{name:18s} {ok:5d} {statistics.median(times):8.1f} {p95:8.1f} {times[-1]:8.1f}')


if __name__ == '__main__':
    main()
