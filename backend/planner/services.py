from __future__ import annotations

from dataclasses import dataclass
from math import floor

from .routing import RouteInfo, point_at_mile


AVERAGE_SPEED_MPH = 55
FUEL_INTERVAL_MILES = 1000
MAX_DAILY_DRIVING_HOURS = 11
MAX_ON_DUTY_WINDOW_HOURS = 14
MAX_DRIVING_BEFORE_BREAK_HOURS = 8
MAX_CYCLE_HOURS = 70
PICKUP_HOURS = 1
DROPOFF_HOURS = 1
FUEL_STOP_HOURS = 0.5
RESTART_HOURS = 34
REQUIRED_OFF_DUTY_HOURS = 10

DUTY_STATUS_BY_TYPE = {
    "driving": "driving",
    "pickup": "onDuty",
    "dropoff": "onDuty",
    "fuel": "onDuty",
    "break": "offDuty",
    "rest": "offDuty",
    "restart": "offDuty",
}


@dataclass(frozen=True)
class TripInput:
    current_location: str
    pickup_location: str
    dropoff_location: str
    current_cycle_used: float


@dataclass
class PlannerState:
    clock: float
    mile_marker: float
    # Assessment input provides current cycle usage, not 8 days of recap history.
    cycle_used: float
    driving_in_window: float
    window_start_time: float | None
    driving_since_break: float
    fuel_stops: int


def build_trip_plan(trip: TripInput, route: RouteInfo) -> dict:
    timeline = build_timeline(trip, route)
    daily_logs = build_daily_logs(timeline, route)
    stops = build_stops(timeline, route)
    planned_drive_hours = sum(event["duration"] for event in timeline if event["type"] == "driving")

    return {
        "summary": {
            "distanceMiles": round(route.distance_miles),
            "driveHours": round(planned_drive_hours, 2),
            "estimatedDriveHours": round(planned_drive_hours, 2),
            "osrmDurationHours": round(route.duration_hours, 2),
            "tripDays": len(daily_logs),
            "estimatedDays": len(daily_logs),
            "fuelStops": len([event for event in timeline if event["type"] == "fuel"]),
            "cycleHoursAvailableAtStart": max(0, round(MAX_CYCLE_HOURS - trip.current_cycle_used, 2)),
            "assumptions": [
                "Property-carrying driver under the 70 hours / 8 days rule.",
                "Pickup, dropoff, and fuel are on-duty not-driving time.",
                "Route distance and geometry come from OpenStreetMap geocoding and OSRM routing.",
                "Planned HOS driving time uses a fixed 55 mph planning speed.",
                "Fuel stop duration is fixed at 30 minutes and occurs at least once every 1,000 miles.",
            ],
        },
        "route": {
            "distanceMiles": round(route.distance_miles, 2),
            "durationHours": round(route.duration_hours, 2),
            "geometry": [coordinate.as_dict() for coordinate in route.geometry],
            "points": [
                {
                    "label": point.label,
                    "location": point.location,
                    "coordinate": point.coordinate.as_dict(),
                    "distanceMiles": round(point.distance_miles, 2),
                }
                for point in route.points
            ],
        },
        "stops": stops,
        "timeline": timeline,
        "dailyLogs": daily_logs,
    }


def build_timeline(trip: TripInput, route: RouteInfo) -> list[dict]:
    state = PlannerState(
        clock=0,
        mile_marker=0,
        cycle_used=trip.current_cycle_used,
        driving_in_window=0,
        window_start_time=None,
        driving_since_break=0,
        fuel_stops=0,
    )
    timeline: list[dict] = []
    pickup_done = False
    dropoff_done = False
    pickup_mile = route.points[1].distance_miles
    dropoff_mile = route.distance_miles

    while not dropoff_done:
        ensure_cycle_available(timeline, state, route)

        if not pickup_done and state.mile_marker >= pickup_mile - 0.1:
            ensure_on_duty_capacity(timeline, state, route, PICKUP_HOURS)
            add_event(timeline, state, route, "pickup", PICKUP_HOURS, "Pickup", trip.pickup_location)
            pickup_done = True
            continue

        if pickup_done and state.mile_marker >= dropoff_mile - 0.1:
            ensure_on_duty_capacity(timeline, state, route, DROPOFF_HOURS)
            add_event(timeline, state, route, "dropoff", DROPOFF_HOURS, "Dropoff", trip.dropoff_location)
            dropoff_done = True
            continue

        next_milestone = next_route_milestone(state, pickup_mile, dropoff_mile, pickup_done)
        if next_milestone <= state.mile_marker + 0.01:
            state.mile_marker = min(dropoff_mile, state.mile_marker + 0.1)
            continue

        if state.driving_since_break >= MAX_DRIVING_BEFORE_BREAK_HOURS:
            add_event(timeline, state, route, "break", 0.5, "30-minute non-driving break")
            state.driving_since_break = 0
            continue

        if state.driving_in_window >= MAX_DAILY_DRIVING_HOURS or remaining_window_hours(state) <= 0:
            add_daily_rest(timeline, state, route)
            continue

        drive_capacity_hours = min(
            MAX_DAILY_DRIVING_HOURS - state.driving_in_window,
            remaining_window_hours(state),
            MAX_DRIVING_BEFORE_BREAK_HOURS - state.driving_since_break,
            MAX_CYCLE_HOURS - state.cycle_used,
        )

        if drive_capacity_hours <= 0:
            if state.cycle_used >= MAX_CYCLE_HOURS:
                ensure_cycle_available(timeline, state, route)
            else:
                add_daily_rest(timeline, state, route)
            continue

        miles_to_drive = min(next_milestone - state.mile_marker, drive_capacity_hours * AVERAGE_SPEED_MPH)
        drive_hours = miles_to_drive / AVERAGE_SPEED_MPH
        add_event(
            timeline,
            state,
            route,
            "driving",
            drive_hours,
            "Drive toward pickup" if not pickup_done else "Drive toward delivery",
            miles=miles_to_drive,
            end_mile=state.mile_marker + miles_to_drive,
        )

        if should_add_fuel_stop(state, route):
            ensure_on_duty_capacity(timeline, state, route, FUEL_STOP_HOURS)
            add_event(timeline, state, route, "fuel", FUEL_STOP_HOURS, "Fuel stop")
            state.fuel_stops += 1

    fill_last_day_with_off_duty(timeline, state, route)
    return timeline


def ensure_cycle_available(timeline: list[dict], state: PlannerState, route: RouteInfo) -> None:
    if state.cycle_used < MAX_CYCLE_HOURS:
        return

    add_restart(timeline, state, route)


def add_restart(timeline: list[dict], state: PlannerState, route: RouteInfo) -> None:
    add_event(timeline, state, route, "restart", RESTART_HOURS, "34-hour cycle restart")
    state.cycle_used = 0
    state.driving_in_window = 0
    state.window_start_time = None
    state.driving_since_break = 0


def ensure_on_duty_capacity(
    timeline: list[dict],
    state: PlannerState,
    route: RouteInfo,
    duration: float,
) -> None:
    if state.cycle_used + duration > MAX_CYCLE_HOURS:
        add_restart(timeline, state, route)
    if remaining_window_hours(state) >= duration:
        return

    add_daily_rest(timeline, state, route)


def add_daily_rest(timeline: list[dict], state: PlannerState, route: RouteInfo) -> None:
    hours_until_next_day = 24 - (state.clock % 24)
    rest_duration = max(REQUIRED_OFF_DUTY_HOURS, hours_until_next_day)
    add_event(timeline, state, route, "rest", rest_duration, "Required 10-hour off-duty reset")
    state.driving_in_window = 0
    state.window_start_time = None
    state.driving_since_break = 0


def remaining_window_hours(state: PlannerState) -> float:
    if state.window_start_time is None:
        return MAX_ON_DUTY_WINDOW_HOURS
    return max(0, MAX_ON_DUTY_WINDOW_HOURS - (state.clock - state.window_start_time))


def next_route_milestone(state: PlannerState, pickup_mile: float, dropoff_mile: float, pickup_done: bool) -> float:
    candidates = [dropoff_mile]
    next_fuel_mile = (state.fuel_stops + 1) * FUEL_INTERVAL_MILES
    if next_fuel_mile < dropoff_mile:
        candidates.append(next_fuel_mile)
    if not pickup_done:
        candidates.append(pickup_mile)
    return min(candidate for candidate in candidates if candidate > state.mile_marker + 0.01)


def should_add_fuel_stop(state: PlannerState, route: RouteInfo) -> bool:
    next_fuel_mile = (state.fuel_stops + 1) * FUEL_INTERVAL_MILES
    return state.mile_marker >= next_fuel_mile - 0.1 and state.mile_marker < route.distance_miles - 0.1


def add_event(
    timeline: list[dict],
    state: PlannerState,
    route: RouteInfo,
    event_type: str,
    duration: float,
    description: str,
    location: str | None = None,
    miles: float = 0,
    end_mile: float | None = None,
) -> None:
    start_time = state.clock
    end_time = state.clock + duration
    if end_mile is None:
        end_mile = state.mile_marker
    coordinate = point_at_mile(route.geometry, end_mile)

    event = {
        "type": event_type,
        "status": DUTY_STATUS_BY_TYPE[event_type],
        "day": floor(start_time / 24) + 1,
        "startTime": start_time,
        "endTime": end_time,
        "startClock": format_clock(start_time),
        "endClock": format_clock(end_time),
        "duration": duration,
        "hours": duration,
        "location": location or approximate_location(event_type, end_mile),
        "coordinate": coordinate.as_dict(),
        "miles": miles,
        "distanceMiles": round(end_mile, 2),
        "description": description,
        "label": description if location is None else f"{description} at {location}",
    }
    timeline.append(event)

    state.clock = end_time
    state.mile_marker = end_mile

    if event_type == "driving":
        if state.window_start_time is None:
            state.window_start_time = start_time
        state.driving_in_window += duration
        state.driving_since_break += duration
        state.cycle_used += duration
    elif DUTY_STATUS_BY_TYPE[event_type] == "onDuty":
        if state.window_start_time is None:
            state.window_start_time = start_time
        state.cycle_used += duration
    elif event_type in {"break", "rest", "restart"}:
        state.driving_since_break = 0


def fill_last_day_with_off_duty(timeline: list[dict], state: PlannerState, route: RouteInfo) -> None:
    remainder = state.clock % 24
    if remainder == 0:
        return
    add_event(timeline, state, route, "rest", 24 - remainder, "Off duty")


def build_daily_logs(timeline: list[dict], route: RouteInfo) -> list[dict]:
    total_days = max(floor(event["endTime"] / 24) + (0 if event["endTime"] % 24 == 0 else 1) for event in timeline)
    logs = []

    for day in range(1, total_days + 1):
        day_start = (day - 1) * 24
        day_end = day * 24
        segments = []
        remarks = []
        totals = {"offDuty": 0.0, "sleeperBerth": 0.0, "driving": 0.0, "onDuty": 0.0}
        miles = 0.0

        for event in timeline:
            overlap_start = max(event["startTime"], day_start)
            overlap_end = min(event["endTime"], day_end)
            if overlap_end <= overlap_start:
                continue

            status = event["status"]
            duration = overlap_end - overlap_start
            totals[status] += duration
            if status == "driving":
                segment_miles = event["miles"] * (duration / event["duration"]) if event["duration"] else 0
                miles += segment_miles
            else:
                segment_miles = 0

            segment = {
                "status": status,
                "type": event["type"],
                "startHour": round(overlap_start - day_start, 2),
                "endHour": round(overlap_end - day_start, 2),
                "duration": round(duration, 2),
                "label": event["description"],
                "location": event["location"],
                "miles": round(segment_miles, 2),
            }
            segments.append(segment)

            if event["type"] in {"pickup", "dropoff", "fuel", "break", "rest", "restart"}:
                remarks.append({
                    "time": format_clock(overlap_start),
                    "text": f"{event['description']} - {event['location']}",
                })

        total = sum(totals.values())
        logs.append({
            "day": day,
            "dateLabel": f"Day {day}",
            "carrier": "Carrier not provided",
            "truck": "Vehicle not provided",
            "route": " -> ".join(point.location for point in route.points),
            "totalHours": round(total, 2),
            "total": round(total, 2),
            "offDuty": round(totals["offDuty"], 2),
            "sleeperBerth": round(totals["sleeperBerth"], 2),
            "driving": round(totals["driving"], 2),
            "onDuty": round(totals["onDuty"], 2),
            "miles": round(miles, 2),
            "segments": segments,
            "remarks": remarks,
        })

    return logs


def build_stops(timeline: list[dict], route: RouteInfo) -> list[dict]:
    stops = [
        {
            "type": "start",
            "label": route.points[0].label,
            "location": route.points[0].location,
            "coordinate": route.points[0].coordinate.as_dict(),
        }
    ]
    for event in timeline:
        if event["type"] in {"pickup", "dropoff", "fuel", "break", "rest", "restart"}:
            stops.append({
                "type": event["type"],
                "label": event["description"],
                "location": event["location"],
                "coordinate": event["coordinate"],
                "day": event["day"],
                "time": event["startClock"],
            })
    return stops


def approximate_location(event_type: str, mile_marker: float) -> str:
    if mile_marker <= 0:
        return "Trip start"
    if event_type == "fuel":
        return f"Near mile {mile_marker:.0f}"
    return f"Route mile {mile_marker:.0f}"


def format_clock(hour: float) -> str:
    day_hour = hour % 24
    hours = int(day_hour)
    minutes = int(round((day_hour - hours) * 60))
    if minutes == 60:
        hours = (hours + 1) % 24
        minutes = 0
    return f"{hours:02d}:{minutes:02d}"
