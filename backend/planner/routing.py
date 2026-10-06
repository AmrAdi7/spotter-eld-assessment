from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, radians, sin, sqrt

import requests


class RoutingError(ValueError):
    pass


@dataclass(frozen=True)
class Coordinate:
    lat: float
    lng: float

    def as_dict(self) -> dict:
        return {"lat": self.lat, "lng": self.lng}


@dataclass(frozen=True)
class RoutePoint:
    label: str
    location: str
    coordinate: Coordinate
    distance_miles: float


@dataclass(frozen=True)
class RouteInfo:
    distance_miles: float
    duration_hours: float
    geometry: list[Coordinate]
    points: list[RoutePoint]


NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OSRM_URL = "https://router.project-osrm.org/route/v1/driving"
METERS_PER_MILE = 1609.344


def build_route(current_location: str, pickup_location: str, dropoff_location: str) -> RouteInfo:
    start = geocode_location(current_location)
    pickup = geocode_location(pickup_location)
    dropoff = geocode_location(dropoff_location)

    coordinates = [start, pickup, dropoff]
    coordinate_path = ";".join(f"{coord.lng},{coord.lat}" for coord in coordinates)
    response = requests.get(
        f"{OSRM_URL}/{coordinate_path}",
        params={
            "overview": "full",
            "geometries": "geojson",
            "steps": "false",
        },
        timeout=20,
    )

    if response.status_code != 200:
        raise RoutingError("Routing service is unavailable right now. Please try again.")

    payload = response.json()
    routes = payload.get("routes") or []
    if not routes:
        raise RoutingError("Could not calculate a driving route for those locations.")

    route = routes[0]
    geometry = [
        Coordinate(lat=lat, lng=lng)
        for lng, lat in route["geometry"]["coordinates"]
    ]
    if len(geometry) < 2:
        raise RoutingError("The routing service returned an incomplete route.")

    waypoint_distances = waypoint_mile_markers(geometry, [start, pickup, dropoff])

    return RouteInfo(
        distance_miles=route["distance"] / METERS_PER_MILE,
        duration_hours=route["duration"] / 3600,
        geometry=geometry,
        points=[
            RoutePoint("Current location", current_location, start, waypoint_distances[0]),
            RoutePoint("Pickup", pickup_location, pickup, waypoint_distances[1]),
            RoutePoint("Dropoff", dropoff_location, dropoff, waypoint_distances[2]),
        ],
    )


def geocode_location(query: str) -> Coordinate:
    response = requests.get(
        NOMINATIM_URL,
        params={"q": query, "format": "json", "limit": 1},
        headers={"User-Agent": "spotter-eld-assessment/1.0"},
        timeout=15,
    )

    if response.status_code != 200:
        raise RoutingError("Geocoding service is unavailable right now. Please try again.")

    results = response.json()
    if not results:
        raise RoutingError(f"Could not find coordinates for '{query}'.")

    return Coordinate(lat=float(results[0]["lat"]), lng=float(results[0]["lon"]))


def point_at_mile(geometry: list[Coordinate], mile_marker: float) -> Coordinate:
    if mile_marker <= 0:
        return geometry[0]

    traveled = 0.0
    for start, end in zip(geometry, geometry[1:]):
        segment_miles = haversine_miles(start, end)
        if traveled + segment_miles >= mile_marker:
            ratio = 0 if segment_miles == 0 else (mile_marker - traveled) / segment_miles
            return Coordinate(
                lat=start.lat + (end.lat - start.lat) * ratio,
                lng=start.lng + (end.lng - start.lng) * ratio,
            )
        traveled += segment_miles

    return geometry[-1]


def waypoint_mile_markers(geometry: list[Coordinate], waypoints: list[Coordinate]) -> list[float]:
    markers = []
    for waypoint in waypoints:
        closest_index = min(
            range(len(geometry)),
            key=lambda index: haversine_miles(geometry[index], waypoint),
        )
        markers.append(sum(
            haversine_miles(geometry[index], geometry[index + 1])
            for index in range(closest_index)
        ))
    return markers


def haversine_miles(first: Coordinate, second: Coordinate) -> float:
    earth_radius_miles = 3958.8
    lat1 = radians(first.lat)
    lat2 = radians(second.lat)
    delta_lat = radians(second.lat - first.lat)
    delta_lng = radians(second.lng - first.lng)

    a = sin(delta_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(delta_lng / 2) ** 2
    return earth_radius_miles * 2 * atan2(sqrt(a), sqrt(1 - a))
