from django.urls import path

from .views import trip_plan


urlpatterns = [
    path("trip-plan/", trip_plan, name="trip-plan"),
]
