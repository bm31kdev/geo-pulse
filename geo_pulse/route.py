"""Calcul d'itinéraires OSRM et interpolation géographique."""
from __future__ import annotations

from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt
from typing import Iterable
import requests


class ErreurItineraire(RuntimeError):
    pass


@dataclass(frozen=True)
class Itineraire:
    points: list[tuple[float, float]]  # latitude, longitude
    distance_m: float
    duree_s: float


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distance haversine entre deux points (lat, lon)."""
    lat1, lon1, lat2, lon2 = map(radians, (*a, *b))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 6_371_000 * 2 * asin(sqrt(h))


def calculer_itineraire(depart: tuple[float, float], destination: tuple[float, float], profil: str) -> Itineraire:
    """Interroge le serveur public OSRM; lève une erreur explicite si indisponible."""
    # OSRM public propose driving; les profils marche/vélo gardent une géométrie routière
    # et la vitesse de lecture est, elle, contrôlée par l'application.
    url = "https://router.project-osrm.org/route/v1/driving/"
    coords = f"{depart[1]},{depart[0]};{destination[1]},{destination[0]}"
    try:
        response = requests.get(url + coords, params={"overview": "full", "geometries": "geojson"}, timeout=15,
                                headers={"User-Agent": "GeoPulse/1.0"})
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        raise ErreurItineraire(f"Impossible de joindre OSRM : {exc}") from exc
    if data.get("code") != "Ok" or not data.get("routes"):
        raise ErreurItineraire(f"OSRM n'a pas trouvé d'itinéraire : {data.get('message', 'réponse inconnue')}")
    route = data["routes"][0]
    return Itineraire([(lat, lon) for lon, lat in route["geometry"]["coordinates"]], route["distance"], route["duration"])


def points_equidistants(points: Iterable[tuple[float, float]], pas_m: float = 8.0) -> list[tuple[float, float]]:
    """Rééchantillonne une polyline : les mises à jour GPS sont régulières et fluides."""
    pts = list(points)
    if len(pts) < 2:
        return pts
    resultat = [pts[0]]
    reste = 0.0
    for debut, fin in zip(pts, pts[1:]):
        segment = distance_m(debut, fin)
        if segment == 0:
            continue
        parcouru = max(pas_m - reste, 0.0)
        while parcouru < segment:
            ratio = parcouru / segment
            resultat.append((debut[0] + (fin[0] - debut[0]) * ratio, debut[1] + (fin[1] - debut[1]) * ratio))
            parcouru += pas_m
        reste = max(0.0, segment - (parcouru - pas_m))
    if resultat[-1] != pts[-1]:
        resultat.append(pts[-1])
    return resultat
