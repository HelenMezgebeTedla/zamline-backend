import json
from dataclasses import dataclass
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from config import ORS_API_KEY, ORS_BASE_URL, ORS_GEOCODE_URL
from models.shipments import Shipment
from services.errors import ExternalServiceError

ORS_PROFILE = "driving-hgv"
REQUEST_TIMEOUT_SECONDS = 15


class RouteUnavailableError(ExternalServiceError):
    pass


class GeocodingUnavailableError(ExternalServiceError):
    pass


@dataclass(frozen=True)
class RouteSummary:
    distance_km: float
    duration_minutes: int


@dataclass(frozen=True)
class GeocodedPlace:
    label: str
    latitude: float
    longitude: float


def parse_route_summary(payload: dict) -> RouteSummary:
    summary = payload["features"][0]["properties"]["summary"]
    return RouteSummary(
        distance_km=round(summary["distance"] / 1000, 2),
        duration_minutes=round(summary["duration"] / 60),
    )


def build_coordinates_directions_url(
    origin_latitude: float,
    origin_longitude: float,
    destination_latitude: float,
    destination_longitude: float,
) -> str:
    query = urlencode(
        {
            "api_key": ORS_API_KEY,
            "start": f"{origin_longitude},{origin_latitude}",
            "end": f"{destination_longitude},{destination_latitude}",
        }
    )
    return f"{ORS_BASE_URL}/{ORS_PROFILE}?{query}"


def get_route_between_coordinates(
    origin_latitude: float,
    origin_longitude: float,
    destination_latitude: float,
    destination_longitude: float,
) -> RouteSummary:
    if not ORS_API_KEY:
        raise RouteUnavailableError("Routing service is not configured")

    url = build_coordinates_directions_url(
        origin_latitude, origin_longitude, destination_latitude, destination_longitude
    )
    try:
        with urlopen(url, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.load(response)
        return parse_route_summary(payload)
    except (URLError, TimeoutError, ValueError, KeyError, IndexError) as error:
        raise RouteUnavailableError("Route could not be calculated") from error


def build_geocode_url(text: str, size: int) -> str:
    query = urlencode({"api_key": ORS_API_KEY, "text": text, "size": size})
    return f"{ORS_GEOCODE_URL}?{query}"


def parse_geocoded_places(payload: dict) -> list[GeocodedPlace]:
    places = []
    for feature in payload["features"]:
        longitude, latitude = feature["geometry"]["coordinates"][:2]
        places.append(
            GeocodedPlace(
                label=feature["properties"]["label"],
                latitude=latitude,
                longitude=longitude,
            )
        )
    return places


def geocode_address(text: str, size: int = 5) -> list[GeocodedPlace]:
    if not ORS_API_KEY:
        raise GeocodingUnavailableError("Geocoding service is not configured")

    try:
        with urlopen(
            build_geocode_url(text, size), timeout=REQUEST_TIMEOUT_SECONDS
        ) as response:
            payload = json.load(response)
        return parse_geocoded_places(payload)
    except (URLError, TimeoutError, ValueError, KeyError, IndexError) as error:
        raise GeocodingUnavailableError("Address could not be geocoded") from error


def geocoding_text(address: str) -> str:
    return address if "zambia" in address.lower() else f"{address}, Zambia"


def locate_address(address: str) -> tuple[float, float]:
    try:
        places = geocode_address(geocoding_text(address), 1)
    except GeocodingUnavailableError as error:
        raise RouteUnavailableError("Route could not be calculated") from error
    if not places:
        raise RouteUnavailableError(f"Could not find {address} on the map")
    return places[0].latitude, places[0].longitude


def shipment_coordinates(shipment: Shipment) -> tuple[float, float, float, float]:
    origin = (shipment.origin_latitude, shipment.origin_longitude)
    destination = (shipment.destination_latitude, shipment.destination_longitude)
    if None in origin:
        origin = locate_address(shipment.origin_address)
    if None in destination:
        destination = locate_address(shipment.destination_address)
    return (*origin, *destination)


def get_route_summary(shipment: Shipment) -> RouteSummary:
    return get_route_between_coordinates(*shipment_coordinates(shipment))
