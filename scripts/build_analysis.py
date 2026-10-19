"""Build (or rebuild) the cached real-data analysis. Used by the Dockerfile and Jenkins.

    python scripts/build_analysis.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.analytics import pipeline  # noqa: E402

if __name__ == '__main__':
    result = pipeline.get(verbose=True)
    o = result['overview']
    print(f"Analysis ready: {o['aircraft']} aircraft, {o['observations_used']} observations, built in {result.get('built_seconds')} s")
