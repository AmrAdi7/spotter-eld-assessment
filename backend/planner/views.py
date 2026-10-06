import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .routing import RoutingError, build_route
from .services import TripInput, build_trip_plan


@csrf_exempt
@require_http_methods(["POST"])
def trip_plan(request):
    try:
        payload = json.loads(request.body or "{}")
        trip = TripInput(
            current_location=clean_required(payload, "currentLocation"),
            pickup_location=clean_required(payload, "pickupLocation"),
            dropoff_location=clean_required(payload, "dropoffLocation"),
            current_cycle_used=float(payload.get("currentCycleUsed", 0)),
        )
    except (TypeError, ValueError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    if trip.current_cycle_used < 0 or trip.current_cycle_used > 70:
        return JsonResponse({"error": "Current cycle used must be between 0 and 70 hours."}, status=400)

    try:
        route = build_route(trip.current_location, trip.pickup_location, trip.dropoff_location)
        return JsonResponse(build_trip_plan(trip, route))
    except RoutingError as exc:
        return JsonResponse({"error": str(exc)}, status=400)


def clean_required(payload: dict, key: str) -> str:
    value = str(payload.get(key, "")).strip()
    if not value:
        raise ValueError(f"{key} is required.")
    return value
