"""Météo du jour via Open-Meteo (gratuit, sans clé)."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Codes temps WMO → formulation parlée
WMO = {
    0: "un ciel dégagé",
    1: "un ciel globalement dégagé",
    2: "des nuages épars",
    3: "un ciel couvert",
    45: "du brouillard",
    48: "du brouillard givrant",
    51: "une bruine légère",
    53: "de la bruine",
    55: "une bruine soutenue",
    56: "une bruine verglaçante",
    57: "une bruine verglaçante soutenue",
    61: "une pluie faible",
    63: "de la pluie",
    65: "une pluie soutenue",
    66: "une pluie verglaçante",
    67: "une pluie verglaçante soutenue",
    71: "de faibles chutes de neige",
    73: "de la neige",
    75: "de fortes chutes de neige",
    77: "des grains de neige",
    80: "de faibles averses",
    81: "des averses",
    82: "de fortes averses",
    85: "des averses de neige",
    86: "de fortes averses de neige",
    95: "un orage",
    96: "un orage avec grêle",
    99: "un orage violent avec grêle",
}


@dataclass
class Weather:
    city: str
    temp_min: float
    temp_max: float
    sky: str  # formulation, ex. « un ciel dégagé »
    rain_prob: int  # %


async def fetch_weather(city: str, client: httpx.AsyncClient | None = None) -> Weather | None:
    """Prévisions du jour pour une ville ; None si le service est indisponible."""
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=10)
    try:
        geo = await client.get(
            GEOCODING_URL, params={"name": city, "count": 1, "language": "fr"}
        )
        geo.raise_for_status()
        results = geo.json().get("results") or []
        if not results:
            return None
        place = results[0]
        forecast = await client.get(
            FORECAST_URL,
            params={
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "daily": "temperature_2m_min,temperature_2m_max,precipitation_probability_max,weather_code",
                "timezone": "auto",
                "forecast_days": 1,
            },
        )
        forecast.raise_for_status()
        daily = forecast.json()["daily"]
        code = daily["weather_code"][0]
        return Weather(
            city=place.get("name", city),
            temp_min=round(daily["temperature_2m_min"][0]),
            temp_max=round(daily["temperature_2m_max"][0]),
            sky=WMO.get(code, "un temps indéterminé"),
            rain_prob=int(daily["precipitation_probability_max"][0] or 0),
        )
    except Exception:
        return None  # la météo ne doit jamais casser l'épisode
    finally:
        if own:
            await client.aclose()


def weather_text(weather: Weather) -> str:
    """Phrase parlée : « Côté météo à Paris : entre 14 et 26 degrés… »"""
    return (
        f"Côté météo à {weather.city} : entre {int(weather.temp_min)} et "
        f"{int(weather.temp_max)} degrés aujourd'hui, avec {weather.sky}. "
        f"Risque de précipitations : {weather.rain_prob} pour cent."
    )
