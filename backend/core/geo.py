"""Geodesy helpers shared by the planner and the real-data analytics.

Distances are in nautical miles (NM), altitudes in feet, angles in degrees.
A local equirectangular projection is accurate to well under 1 % inside the
roughly 300 NM London-Amsterdam box, which is sufficient for screening.
"""
from __future__ import annotations

import math

EARTH_RADIUS_NM = 3440.065
NM_PER_DEG_LAT = 60.0


def haversine_nm(lat1, lon1, lat2, lon2):
    """Great-circle distance in NM."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_NM * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1, lon1, lat2, lon2):
    """Initial true bearing from point 1 to point 2."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(y, x)) % 360


def angle_diff(a, b):
    """Signed smallest difference b - a in degrees, range (-180, 180]."""
    return (b - a + 540.0) % 360.0 - 180.0


class Projection:
    """Local tangent-plane projection: x east, y north, both in NM."""

    def __init__(self, lat0: float, lon0: float):
        self.lat0 = lat0
        self.lon0 = lon0
        self.kx = NM_PER_DEG_LAT * math.cos(math.radians(lat0))

    def to_xy(self, lat, lon):
        return (lon - self.lon0) * self.kx, (lat - self.lat0) * NM_PER_DEG_LAT

    def to_latlon(self, x, y):
        return self.lat0 + y / NM_PER_DEG_LAT, self.lon0 + x / self.kx


# Centre of the bundled London-Amsterdam recording.
LONDON = Projection(52.0, 0.5)
