"""Validated coordinates and area-uniform, one-shot geodesic offsets."""
import math
import random

EARTH_RADIUS_M = 6_371_008.8
MAX_RADIUS_M = 100_000


def number(value, name):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a finite number") from None
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def coordinates(latitude, longitude):
    lat = number(latitude, "latitude")
    lng = number(longitude, "longitude")
    if not -90 <= lat <= 90 or not -180 <= lng <= 180:
        raise ValueError("Latitude must be within [-90, 90], longitude within [-180, 180]")
    return {"lat": lat, "lng": lng}


def radius_m(value):
    radius = number(value, "radius")
    if not 0 <= radius <= MAX_RADIUS_M:
        raise ValueError(f"Radius must be within [0, {MAX_RADIUS_M}] metres")
    return radius


def random_offset(base, radius, rng=None):
    """Return a new point; never mutate the saved centre, including at the poles."""
    centre = coordinates(base["lat"], base["lng"])
    radius = radius_m(radius)
    if radius == 0:
        return centre
    rng = rng or random.SystemRandom()
    angular_distance = radius * math.sqrt(rng.random()) / EARTH_RADIUS_M
    bearing = 2 * math.pi * rng.random()
    lat, lng = map(math.radians, (centre["lat"], centre["lng"]))
    # Rotate along north/east tangent vectors. Unlike longitude-only formulae,
    # this remains well defined when the centre is exactly at either pole.
    north = (-math.sin(lat) * math.cos(lng), -math.sin(lat) * math.sin(lng), math.cos(lat))
    east = (-math.sin(lng), math.cos(lng), 0)
    origin = (math.cos(lat) * math.cos(lng), math.cos(lat) * math.sin(lng), math.sin(lat))
    point = [math.cos(angular_distance) * origin[i] + math.sin(angular_distance) *
             (math.cos(bearing) * north[i] + math.sin(bearing) * east[i]) for i in range(3)]
    return {"lat": math.degrees(math.atan2(point[2], math.hypot(point[0], point[1]))),
            "lng": (math.degrees(math.atan2(point[1], point[0])) + 180) % 360 - 180}
