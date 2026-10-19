"""Record a multi-frame OpenSky dataset in the same format as the bundled London-Amsterdam recording.

Example (needs internet access to opensky-network.org):
    python scripts/record_opensky.py --minutes 90 --interval 15 --out data/my_recording.json.gz

Optional OAuth client credentials are read from OPENSKY_CLIENT_ID / OPENSKY_CLIENT_SECRET (.env).
Derived speed, heading and vertical rate are computed from successive positions, exactly as in the
bundled file, so the analysis pipeline can use the result directly (set SKYCONTROL_DATA_DIR or replace
data/london_amsterdam_opensky.json.gz and delete data/cache).
"""
import argparse
import gzip
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.opensky import fetch_live  # noqa: E402


def bearing(lat1, lon1, lat2, lon2):
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(y, x)) % 360


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--minutes', type=float, default=90)
    ap.add_argument('--interval', type=float, default=15, help='seconds between requests (anonymous users: >= 10)')
    ap.add_argument('--bounds', default='49.5,54.5,-2.0,3.0', help='lamin,lamax,lomin,lomax')
    ap.add_argument('--out', default='data/opensky_recording.json.gz')
    args = ap.parse_args()
    lamin, lamax, lomin, lomax = map(float, args.bounds.split(','))
    bounds = {'lamin': lamin, 'lamax': lamax, 'lomin': lomin, 'lomax': lomax}
    end = time.time() + args.minutes * 60
    observations, last = [], {}
    while time.time() < end:
        try:
            raw = fetch_live(bounds)
        except Exception as exc:  # keep recording through transient failures, never invent data
            print('request failed:', exc)
            time.sleep(args.interval)
            continue
        ts = int(raw.get('time') or time.time())
        for s in raw.get('states') or []:
            icao, callsign, lon, lat, baro, ground = s[0], (s[1] or '').strip() or None, s[5], s[6], s[7], bool(s[8])
            if lat is None or lon is None:
                continue
            alt = round(baro * 3.28084) if baro is not None else None
            row = {'timestamp_unix_utc': ts, 'timestamp_utc': datetime.fromtimestamp(ts, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                   'icao24': icao, 'callsign': callsign, 'latitude': lat, 'longitude': lon, 'altitude_ft': alt, 'on_ground': ground,
                   'derived_speed_kt': None, 'derived_heading_deg': None, 'derived_vertical_rate_fpm': None}
            prev = last.get(icao)
            if prev and ts > prev['timestamp_unix_utc']:
                dt = ts - prev['timestamp_unix_utc']
                dy = (lat - prev['latitude']) * 60
                dx = (lon - prev['longitude']) * 60 * math.cos(math.radians(lat))
                row['derived_speed_kt'] = round(math.hypot(dx, dy) / dt * 3600, 1)
                row['derived_heading_deg'] = round(bearing(prev['latitude'], prev['longitude'], lat, lon), 1)
                if alt is not None and prev['altitude_ft'] is not None:
                    row['derived_vertical_rate_fpm'] = round((alt - prev['altitude_ft']) / dt * 60, 1)
            last[icao] = row
            observations.append(row)
        print(f'{datetime.now(timezone.utc):%H:%M:%S} frame {ts}: {len(raw.get("states") or [])} aircraft, {len(observations)} total')
        time.sleep(args.interval)
    times = [o['timestamp_unix_utc'] for o in observations]
    out = {'format': 'skycontrol.opensky.recording.v1', 'metadata': {
        'dataset_name': f'OpenSky recording {args.bounds}', 'source_provider': 'OpenSky Network', 'is_real_recorded_data': True,
        'is_live_data': False, 'observation_count': len(observations), 'distinct_aircraft_count': len({o['icao24'] for o in observations}),
        'timestamped_frames_count': len(set(times)),
        'start_utc': datetime.fromtimestamp(min(times), timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ') if times else None,
        'end_utc': datetime.fromtimestamp(max(times), timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ') if times else None,
        'bounding_box': {'latitude_min': lamin, 'latitude_max': lamax, 'longitude_min': lomin, 'longitude_max': lomax},
        'limitations': ['Derived speed, heading and vertical rate are estimates from successive positions.']},
        'observations': observations}
    path = Path(args.out)
    with (gzip.open(path, 'wt') if path.suffix == '.gz' else open(path, 'w')) as fp:
        json.dump(out, fp)
    print('saved', path, len(observations), 'observations')


if __name__ == '__main__':
    main()
