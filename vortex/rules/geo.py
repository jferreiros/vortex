"""Turning a spoken street address into the nearest site that can serve it.

Problem 15 gives a real Madrid-area address and no site name. Ground truth is
the smallest straight-line distance to the coordinates the clinic publishes,
among the sites that can actually serve the request — and winners win by a
clear margin, so the address only has to land in the right part of the city.

Two layers, in order:

1. **A gazetteer**, below: the municipalities of the Madrid area and the city's
   main streets and districts. No network, deterministic, and enough for a
   margin measured in kilometres.
2. **A live geocoder**, when ``Settings.geocoder_url`` (``VORTEX_GEOCODER_URL``)
   names a Nominatim-compatible endpoint. Off by default so that evals and
   offline work never depend on a network call, and so nothing leaks a
   caller's address to a third party unless the team turned it on
   deliberately.

If neither places the address, the site whose own published address shares the
most words with it answers. A caller who gives an address we cannot place is
not a refusal: it is a question to ask them.
"""

from __future__ import annotations

import math
import re
import unicodedata
from functools import lru_cache
from typing import Any

from vortex.settings import Settings, get_settings

EARTH_RADIUS_KM = 6371.0088

GEOCODER_TIMEOUT_SECS = 3.0


def fold(text: str) -> str:
    """Lower-cased, accent-folded, punctuation-free, single-spaced."""
    stripped = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in stripped if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", stripped.lower())).strip()


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Straight-line distance between two (lat, lon) pairs, in kilometres."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


#: Municipalities of the Madrid area, at their town centres. A caller who names
#: their town has told us enough: the sites are tens of kilometres apart.
MUNICIPALITIES: dict[str, tuple[float, float]] = {
    "getafe": (40.3082, -3.7325),
    "leganes": (40.3281, -3.7644),
    "alcorcon": (40.3459, -3.8248),
    "mostoles": (40.3223, -3.8649),
    "fuenlabrada": (40.2842, -3.7942),
    "parla": (40.2378, -3.7680),
    "pinto": (40.2417, -3.6994),
    "valdemoro": (40.1907, -3.6757),
    "humanes de madrid": (40.2530, -3.8283),
    "alcala de henares": (40.4819, -3.3635),
    "torrejon de ardoz": (40.4590, -3.4795),
    "coslada": (40.4237, -3.5613),
    "san fernando de henares": (40.4234, -3.5322),
    "rivas vaciamadrid": (40.3284, -3.5188),
    "arganda del rey": (40.3013, -3.4370),
    "alcobendas": (40.5405, -3.6318),
    "san sebastian de los reyes": (40.5470, -3.6257),
    "tres cantos": (40.6014, -3.7107),
    "colmenar viejo": (40.6586, -3.7660),
    "pozuelo de alarcon": (40.4335, -3.8133),
    "majadahonda": (40.4735, -3.8722),
    "las rozas": (40.4923, -3.8737),
    "boadilla del monte": (40.4058, -3.8775),
    "villaviciosa de odon": (40.3574, -3.9003),
    "collado villalba": (40.6345, -4.0043),
    "aranjuez": (40.0312, -3.6032),
    "villalba": (40.6345, -4.0043),
    "madrid": (40.4168, -3.7038),
}

#: Streets, squares and districts of the city itself, at a point on them. A
#: long avenue is pinned where its numbering mostly runs, not at its start.
CITY_PLACES: dict[str, tuple[float, float]] = {
    # Centre
    "calle del arenal": (40.4175, -3.7065),
    "puerta del sol": (40.4169, -3.7033),
    "gran via": (40.4200, -3.7057),
    "plaza mayor": (40.4155, -3.7074),
    "calle mayor": (40.4157, -3.7100),
    "calle de alcala": (40.4207, -3.6930),
    "calle de atocha": (40.4114, -3.6987),
    "paseo del prado": (40.4148, -3.6924),
    "calle de toledo": (40.4093, -3.7092),
    "calle de fuencarral": (40.4272, -3.7014),
    "malasana": (40.4258, -3.7036),
    "lavapies": (40.4086, -3.7003),
    "la latina": (40.4113, -3.7107),
    "chueca": (40.4226, -3.6975),
    "embajadores": (40.4053, -3.7016),
    "arganzuela": (40.3985, -3.6955),
    "usera": (40.3818, -3.7069),
    "carabanchel": (40.3835, -3.7290),
    "latina": (40.3928, -3.7480),
    "villaverde": (40.3480, -3.7080),
    "vallecas": (40.3903, -3.6486),
    "puente de vallecas": (40.3903, -3.6636),
    "moratalaz": (40.4070, -3.6435),
    "retiro": (40.4120, -3.6830),
    "salamanca": (40.4270, -3.6800),
    "goya": (40.4250, -3.6770),
    "chamberi": (40.4360, -3.7020),
    "tetuan": (40.4600, -3.6980),
    "chamartin": (40.4620, -3.6800),
    "hortaleza": (40.4700, -3.6420),
    "barajas": (40.4740, -3.5800),
    "ciudad lineal": (40.4450, -3.6490),
    "san blas": (40.4290, -3.6120),
    "fuencarral el pardo": (40.4900, -3.7100),
    "moncloa": (40.4350, -3.7190),
    "aravaca": (40.4560, -3.7880),
    # The long north-south axis, where the high numbers run.
    "paseo de la castellana": (40.4500, -3.6895),
    "castellana": (40.4500, -3.6895),
    "paseo de la habana": (40.4560, -3.6830),
    "nuevos ministerios": (40.4460, -3.6920),
    "plaza de castilla": (40.4667, -3.6890),
    "bernabeu": (40.4531, -3.6883),
    "cuzco": (40.4580, -3.6900),
    "plaza de colon": (40.4255, -3.6900),
    "avenida de america": (40.4400, -3.6720),
    "arturo soria": (40.4530, -3.6450),
    "principe de vergara": (40.4380, -3.6780),
    "serrano": (40.4330, -3.6870),
    "bravo murillo": (40.4560, -3.7020),
    "avenida de la ilustracion": (40.4820, -3.7080),
    "sanchinarro": (40.4900, -3.6600),
    "las tablas": (40.5080, -3.6700),
    "montecarmelo": (40.4980, -3.7000),
    # South-bound roads, the Getafe side.
    "paseo de las delicias": (40.4010, -3.6930),
    "legazpi": (40.3900, -3.6950),
    "avenida de andalucia": (40.3600, -3.6980),
    "plaza eliptica": (40.3850, -3.7180),
    "oporto": (40.3890, -3.7290),
}

#: One table, longest key first: "calle de madrid, getafe" must read as Getafe
#: and not as the city of Madrid.
GAZETTEER: dict[str, tuple[float, float]] = {**MUNICIPALITIES, **CITY_PLACES}

#: Words that carry no location and would otherwise match a site's address.
_NOISE = frozenset(
    {
        "calle",
        "c",
        "avenida",
        "avda",
        "av",
        "paseo",
        "plaza",
        "pza",
        "ronda",
        "carretera",
        "camino",
        "numero",
        "num",
        "n",
        "piso",
        "puerta",
        "bajo",
        "escalera",
        "de",
        "del",
        "la",
        "las",
        "el",
        "los",
        "y",
    }
)


def gazetteer_lookup(address: str) -> tuple[float, float] | None:
    """The most specific gazetteer entry the address mentions."""
    text = fold(address)
    best: tuple[int, tuple[float, float]] | None = None
    for name, point in GAZETTEER.items():
        if re.search(rf"\b{re.escape(name)}\b", text) and (best is None or len(name) > best[0]):
            best = (len(name), point)
    return best[1] if best else None


async def geocode_live(
    address: str, settings: Settings | None = None
) -> tuple[float, float] | None:
    """Ask a Nominatim-compatible endpoint. ``None`` unless one is configured."""
    url = (settings or get_settings()).geocoder_url
    if not url:
        return None
    import httpx  # local: the offline path must not need it

    params = {"q": address, "format": "json", "limit": 1, "countrycodes": "es"}
    try:
        async with httpx.AsyncClient(timeout=GEOCODER_TIMEOUT_SECS) as http:
            response = await http.get(
                url, params=params, headers={"User-Agent": "vortex-clinic-agent/1.0"}
            )
            if response.status_code >= 400:
                return None
            hits = response.json()
    except Exception:  # noqa: BLE001 - a geocoder outage must not lose the call
        return None
    if not hits:
        return None
    try:
        return float(hits[0]["lat"]), float(hits[0]["lon"])
    except (KeyError, TypeError, ValueError):
        return None


@lru_cache(maxsize=512)
def _address_words(address: str) -> frozenset[str]:
    return frozenset(w for w in fold(address).split() if w not in _NOISE and not w.isdigit())


def address_overlap(caller: str, site_address: str) -> int:
    """How many meaningful words two addresses share. The last resort."""
    return len(_address_words(caller) & _address_words(site_address))


async def locate(address: str, settings: Settings | None = None) -> tuple[float, float] | None:
    """Coordinates for a spoken address: gazetteer first, then a live geocoder."""
    return gazetteer_lookup(address) or await geocode_live(address, settings)


def nearest(point: tuple[float, float], sites: list[Any]) -> tuple[Any, float] | None:
    """The site closest to ``point``, with its distance. Sites need coordinates."""
    placed = [s for s in sites if s.latitude is not None and s.longitude is not None]
    if not placed:
        return None
    best = min(placed, key=lambda s: haversine_km(point, (s.latitude, s.longitude)))
    return best, haversine_km(point, (best.latitude, best.longitude))
