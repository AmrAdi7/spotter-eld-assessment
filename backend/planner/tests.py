import json

from django.test import Client, TestCase

from .routing import Coordinate, RouteInfo, RoutePoint
from .services import (
    PlannerState,
    TripInput,
    add_event,
    build_trip_plan,
    remaining_window_hours,
)


def synthetic_route(distance_miles: float) -> RouteInfo:
    start = Coordinate(0, 0)
    end = Coordinate(0, distance_miles / 69)
    return RouteInfo(
        distance_miles=distance_miles,
        duration_hours=distance_miles / 55,
        geometry=[start, end],
        points=[
            RoutePoint("Current location", "Start", start, 0),
            RoutePoint("Pickup", "Pickup", start, 0),
            RoutePoint("Dropoff", "Dropoff", end, distance_miles),
        ],
    )


def plan_for(distance_miles: float, cycle_used: float = 0) -> dict:
    return build_trip_plan(
        TripInput("Start", "Pickup", "Dropoff", cycle_used),
        synthetic_route(distance_miles),
    )


class HosPlannerTests(TestCase):
    def test_14_hour_window_uses_elapsed_clock_time(self):
        route = synthetic_route(1000)
        state = PlannerState(
            clock=0,
            mile_marker=0,
            cycle_used=0,
            driving_in_window=0,
            window_start_time=None,
            driving_since_break=0,
            fuel_stops=0,
        )
        timeline = []

        add_event(timeline, state, route, "driving", 4, "Drive", miles=220, end_mile=220)
        add_event(timeline, state, route, "break", 5, "Off duty")

        self.assertEqual(state.clock, 9)
        self.assertEqual(remaining_window_hours(state), 5)

    def test_11_hour_limit_allows_8_break_3(self):
        plan = plan_for(605)
        driving_events = [event for event in plan["timeline"] if event["type"] == "driving"]

        self.assertEqual([event["duration"] for event in driving_events], [8, 3])
        self.assertEqual(sum(event["duration"] for event in driving_events), 11)
        self.assertEqual(plan["dailyLogs"][0]["driving"], 11)

    def test_30_minute_break_uses_accumulated_driving_segments(self):
        plan = plan_for(1800)
        events = plan["timeline"]
        first_fuel_index = next(index for index, event in enumerate(events) if event["type"] == "fuel")
        first_break_after_fuel = next(
            index for index, event in enumerate(events[first_fuel_index:], start=first_fuel_index)
            if event["type"] == "break"
        )
        driving_since_previous_break = sum(
            event["duration"]
            for event in events[:first_break_after_fuel]
            if event["type"] == "driving"
        ) - 11

        self.assertAlmostEqual(driving_since_previous_break, 8)
        self.assertEqual(events[first_break_after_fuel]["duration"], 0.5)

    def test_fuel_stop_boundaries(self):
        expected = {
            925: 0,
            1000: 0,
            1001: 1,
            1800: 1,
            2000: 1,
            2001: 2,
            2500: 2,
        }

        for miles, fuel_stops in expected.items():
            with self.subTest(miles=miles):
                plan = plan_for(miles)
                self.assertEqual(plan["summary"]["fuelStops"], fuel_stops)
                self.assertEqual(
                    len([event for event in plan["timeline"] if event["type"] == "fuel"]),
                    fuel_stops,
                )

    def test_pickup_and_dropoff_are_on_duty_not_driving(self):
        plan = plan_for(20)
        pickup = next(event for event in plan["timeline"] if event["type"] == "pickup")
        dropoff = next(event for event in plan["timeline"] if event["type"] == "dropoff")

        self.assertEqual(pickup["status"], "onDuty")
        self.assertEqual(dropoff["status"], "onDuty")
        self.assertEqual(pickup["duration"], 1)
        self.assertEqual(dropoff["duration"], 1)

    def test_daily_logs_total_24_hours_for_multi_day_trip(self):
        plan = plan_for(2500)

        self.assertGreater(len(plan["dailyLogs"]), 1)
        for log in plan["dailyLogs"]:
            self.assertEqual(log["totalHours"], 24)

    def test_summary_drive_hours_match_timeline_driving(self):
        plan = plan_for(1800)
        timeline_driving = sum(event["duration"] for event in plan["timeline"] if event["type"] == "driving")

        self.assertEqual(plan["summary"]["driveHours"], round(timeline_driving, 2))

    def test_cycle_shortage_triggers_34_hour_restart_before_work(self):
        plan = plan_for(20, cycle_used=69.5)

        self.assertEqual(plan["timeline"][0]["type"], "restart")
        self.assertEqual(plan["timeline"][0]["duration"], 34)

    def test_invalid_cycle_over_70_returns_validation_error(self):
        response = Client().post(
            "/api/trip-plan/",
            data=json.dumps({
                "currentLocation": "Start",
                "pickupLocation": "Pickup",
                "dropoffLocation": "Dropoff",
                "currentCycleUsed": 70.1,
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Current cycle used must be between 0 and 70 hours.")
