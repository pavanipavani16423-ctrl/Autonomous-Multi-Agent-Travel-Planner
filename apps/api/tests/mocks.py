"""Recorded-style payloads for every external API, served through httpx.MockTransport (no network)."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from urllib.parse import parse_qs, unquote

import httpx

CITIES = {
    "kyoto": {"name": "Kyoto", "country": "Japan", "country_code": "JP", "admin1": "Kyoto",
              "latitude": 35.02107, "longitude": 135.75385, "population": 1463723, "timezone": "Asia/Tokyo"},
    "ljubljana": {"name": "Ljubljana", "country": "Slovenia", "country_code": "SI", "admin1": "Ljubljana",
                  "latitude": 46.05108, "longitude": 14.50513, "population": 255115, "timezone": "Europe/Ljubljana"},
    "nowhereville": {"name": "Nowhereville", "country": "Atlantis", "country_code": "XX", "admin1": "",
                     "latitude": 10.0, "longitude": 10.0, "population": 100, "timezone": "UTC"},
    "mumbai": {"name": "Mumbai", "country": "India", "country_code": "IN", "admin1": "Maharashtra",
               "latitude": 19.07283, "longitude": 72.88261, "population": 12691836, "timezone": "Asia/Kolkata"},
    "bangalore": {"name": "Bangalore Town", "country": "Pakistan", "country_code": "PK", "admin1": "Sindh",
                  "latitude": 24.87, "longitude": 67.08, "timezone": "Asia/Karachi", "feature_code": "PPLX"},
    "paris": {"name": "Paris", "country": "France", "country_code": "FR", "admin1": "Ile-de-France",
              "latitude": 48.85341, "longitude": 2.3488, "population": 2138551, "timezone": "Europe/Paris"},
}

KYOTO_POIS = [
    ("Kinkaku-ji", "tourism", "attraction", 35.0394, 135.7292, "Kita Ward"),
    ("Kiyomizu-dera", "amenity", "place_of_worship", 34.9949, 135.7850, "Higashiyama Ward"),
    ("Fushimi Inari-taisha", "amenity", "place_of_worship", 34.9671, 135.7727, "Fushimi Ward"),
    ("Kyoto National Museum", "tourism", "museum", 34.9899, 135.7732, "Higashiyama Ward"),
    ("Nijo Castle", "tourism", "attraction", 35.0142, 135.7482, "Nakagyo Ward"),
    ("Maruyama Park", "leisure", "park", 35.0036, 135.7809, "Higashiyama Ward"),
    ("Kyoto International Manga Museum", "tourism", "museum", 35.0117, 135.7595, "Nakagyo Ward"),
    ("Ginkaku-ji", "tourism", "attraction", 35.0270, 135.7982, "Sakyo Ward"),
    ("Arashiyama Bamboo Grove", "tourism", "attraction", 35.0170, 135.6713, "Ukyo Ward"),
]
KYOTO_FOOD = [
    ("Nishiki Market", "amenity", "restaurant", 35.0050, 135.7649, "Nakagyo Ward", {"cuisine": "japanese"}),
    ("Shigetsu", "amenity", "restaurant", 35.0156, 135.6738, "Ukyo Ward",
     {"cuisine": "shojin_ryori", "diet:vegetarian": "only", "diet:vegan": "yes"}),
    ("Ippudo Nishiki", "amenity", "restaurant", 35.0047, 135.7640, "Nakagyo Ward", {"cuisine": "ramen"}),
    ("Cafe Bibliotic Hello!", "amenity", "cafe", 35.0145, 135.7660, "Nakagyo Ward", {"diet:vegetarian": "yes"}),
    ("Omen Ginkakuji", "amenity", "restaurant", 35.0248, 135.7940, "Sakyo Ward", {"cuisine": "udon"}),
    ("Yudofu Sagano", "amenity", "restaurant", 35.0140, 135.6760, "Ukyo Ward",
     {"cuisine": "tofu", "diet:vegetarian": "yes"}),
]
KYOTO_STAYS = [
    ("Hotel Granvia Kyoto", "tourism", "hotel", 34.9858, 135.7588, "Shimogyo Ward", {"stars": "4"}),
    ("Piece Hostel Sanjo", "tourism", "hostel", 35.0089, 135.7712, "Nakagyo Ward", {}),
    ("Guest House Kioto", "tourism", "guest_house", 35.0200, 135.7500, "Kamigyo Ward", {}),
    ("Hotel The Mitsui Kyoto", "tourism", "hotel", 35.0128, 135.7516, "Nakagyo Ward", {"stars": "5"}),
]

LJUBLJANA_ARTICLE = """Ljubljana is the capital of Slovenia, a green, walkable city with a castle on a hill and a \
river lined with cafes. The old town is car-free and compact, with baroque churches and bridges by Plecnik.

== Get in ==
Ljubljana Joze Pucnik Airport is 26 km north of the city; shuttle buses and the public bus 28 connect it with \
the main bus station in about 45 minutes. Trains arrive from Zagreb, Vienna and Venice at the central station.

== Get around ==
The centre is best explored on foot. The BicikeLJ bike-share system has stations all over town and the \
Urbana card covers the city buses and the funicular to Ljubljana Castle.

== See ==
Ljubljana Castle sits above the old town; take the funicular or walk up through the forest. Preseren Square \
and the Triple Bridge are the heart of the city. The Dragon Bridge is guarded by four copper dragons.
The National Gallery of Slovenia holds the national art collection and is a good rainy-day visit.

== Do ==
Tivoli Park is the largest park in the city, with walking trails up Roznik hill. Take a boat ride along the \
Ljubljanica river from the Butchers' Bridge. Metelkova is an autonomous cultural centre with street art and bars.

== Eat ==
The Central Market (Odprta kuhna on Fridays in summer) is the best place to try local food from many stalls. \
Try struklji, kranjska klobasa sausages and potica cake. Many restaurants along the river serve vegetarian dishes.

== Sleep ==
Hostel Celica is a former prison turned design hostel in Metelkova. Mid-range hotels cluster around the \
old town and near the railway station; luxury options include the Grand Hotel Union.

== Stay safe ==
Ljubljana is one of the safest capitals in Europe. Watch for cyclists on the riverside paths and keep an eye on \
bags in crowded summer events.
"""


def _daily(params: dict[str, str]) -> dict:
    s, e = date.fromisoformat(params["start_date"]), date.fromisoformat(params["end_date"])
    days = [(s + timedelta(days=i)) for i in range((e - s).days + 1)]
    wet = {1}  # the second day is rainy
    return {"daily": {
        "time": [d.isoformat() for d in days],
        "weather_code": [63 if i in wet else 1 for i in range(len(days))],
        "temperature_2m_max": [17.0 + i % 3 for i in range(len(days))],
        "temperature_2m_min": [8.0 + i % 2 for i in range(len(days))],
        "precipitation_sum": [12.0 if i in wet else 0.0 for i in range(len(days))],
        "precipitation_probability_max": [90 if i in wet else 10 for i in range(len(days))],
    }}


def _element(i: int, name: str, key: str, value: str, lat: float, lon: float, area: str, extra: dict) -> dict:
    return {"type": "node", "id": 1000 + i, "lat": lat, "lon": lon,
            "tags": {"name": name, key: value, "addr:suburb": area, "wikidata": f"Q{i}", **extra}}


def _overpass(query: str) -> dict:
    m = re.search(r"around:\d+,([-\d.]+),([-\d.]+)", query)
    lat, lon = (float(m.group(1)), float(m.group(2))) if m else (0.0, 0.0)
    near_kyoto = abs(lat - 35.02) < 0.5
    rows: list[dict] = []
    if near_kyoto:
        if '"tourism"="hotel"' in query or '"tourism"="hostel"' in query:
            rows += [_element(i, *s) for i, s in enumerate(KYOTO_STAYS)]
        if '"amenity"="restaurant"' in query:
            rows += [_element(100 + i, *f) for i, f in enumerate(KYOTO_FOOD)]
        if '"tourism"="museum"' in query or '"tourism"="attraction"' in query:
            rows += [_element(200 + i, *p, {}) for i, p in enumerate(KYOTO_POIS)]
    else:  # generic city: a few named places around the centre
        base = [("Old Town Square", "tourism", "attraction"), ("City Museum", "tourism", "museum"),
                ("Central Park", "leisure", "park"), ("River Bistro", "amenity", "restaurant"),
                ("Market Hall", "amenity", "restaurant"), ("Hotel Central", "tourism", "hotel"),
                ("Hostel Celica", "tourism", "hostel")]
        for i, (n, k, v) in enumerate(base):
            rows.append(_element(300 + i, n, k, v, lat + 0.002 * i, lon + 0.002 * i, "Centre", {}))
    return {"elements": rows}


def handler(request: httpx.Request) -> httpx.Response:
    url = request.url
    host, path = url.host, url.path
    params = {k: v[0] for k, v in parse_qs(url.query.decode()).items()}
    if host == "geocoding-api.open-meteo.com":
        city = CITIES.get(params.get("name", "").lower())
        return httpx.Response(200, json={"results": [city]} if city else {})
    if host == "api.open-meteo.com" or host == "archive-api.open-meteo.com":
        return httpx.Response(200, json=_daily(params))
    if "overpass" in host:
        body = parse_qs(request.content.decode())
        return httpx.Response(200, json=_overpass(unquote(body.get("data", [""])[0])))
    if host == "photon.komoot.io":
        lat, lon = float(params.get("lat", 35.02)), float(params.get("lon", 135.75))
        q = params.get("q", "place")
        return httpx.Response(200, json={"features": [{
            "geometry": {"coordinates": [lon + 0.004, lat + 0.003]},
            "properties": {"name": q, "country": "Japan", "countrycode": "JP", "osm_id": 777, "osm_type": "N",
                           "osm_value": "attraction", "city": "Kyoto"}}]})
    if host == "nominatim.openstreetmap.org":
        if params.get("featureType") == "settlement":
            hit = {"Bangalore": ("Bengaluru", 12.9768, 77.5901, "India", "in")}.get(params.get("q", ""))
            if not hit:
                return httpx.Response(200, json=[])
            return httpx.Response(200, json=[{"name": hit[0], "lat": str(hit[1]), "lon": str(hit[2]),
                                              "importance": 0.75, "address": {"country": hit[3], "country_code": hit[4]}}])
        box = [float(x) for x in params.get("viewbox", "135.7,35.05,135.8,35.0").split(",")]
        lat, lon = (box[1] + box[3]) / 2, (box[0] + box[2]) / 2
        word = params.get("q", "place")
        cat = {"hotel": ("tourism", "hotel"), "restaurant": ("amenity", "restaurant"),
               "museum": ("tourism", "museum")}.get(word, ("tourism", "attraction"))
        return httpx.Response(200, json=[{"name": f"Nominatim {word.title()}", "lat": str(lat), "lon": str(lon),
                                          "category": cat[0], "type": cat[1], "osm_type": "node", "osm_id": 4242,
                                          "importance": 0.3, "extratags": {}, "address": {"suburb": "Centre"}}])
    if host == "api.frankfurter.dev":
        rates = {"JPY": 150.0, "USD": 1.0, "EUR": 0.9, "INR": 85.0, "GBP": 0.78}
        base, sym = params.get("base", "USD"), params.get("symbols", "USD")
        if base not in rates or sym not in rates:
            return httpx.Response(404, json={"message": "not found"})
        return httpx.Response(200, json={"base": base, "rates": {sym: rates[sym] / rates[base]}})
    if host == "en.wikivoyage.org":
        title = params.get("titles", "")
        if title.lower() == "ljubljana":
            page = {"pageid": 1, "title": "Ljubljana", "extract": LJUBLJANA_ARTICLE}
        else:
            page = {"title": title, "missing": ""}
        return httpx.Response(200, json={"query": {"pages": {"1": page}}})
    if host == "en.wikipedia.org":
        return httpx.Response(200, json={"type": "standard", "thumbnail": {
            "source": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/City.jpg/320px-City.jpg"}})
    return httpx.Response(404, json={"error": f"unmocked {host}{path}"})


def failing_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(503, text="down")


def transport(fn=handler) -> httpx.MockTransport:
    return httpx.MockTransport(fn)


def dumps(o: object) -> str:
    return json.dumps(o)
