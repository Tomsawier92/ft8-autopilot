"""Maidenhead lokátor → földrajzi leírás (offline GeoNames index)."""
from __future__ import annotations

import io
import re
import threading
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.request import urlopen

import numpy as np
from scipy.spatial import cKDTree

from PyFT8.databases import grid_to_latlong

from cw_discover.ft8.callsign import is_callsign as _callsign_is_callsign, normalize_callsign
from cw_discover.ft8.home_qth import HomeQth

GRID4_RE = re.compile(r"^[A-R]{2}[0-9]{2}$")
REPORT_RE = re.compile(r"^(R{1,3}|R[+-]?\d{1,2}|73|RR73|[+-]?\d{1,2})$", re.I)

from cw_discover.paths import STATE_DIR as DATA_DIR
CITIES_URL = "https://download.geonames.org/export/dump/cities15000.zip"
ADMIN1_URL = "https://download.geonames.org/export/dump/admin1CodesASCII.txt"
COUNTRY_URL = "https://download.geonames.org/export/dump/countryInfo.txt"
INDEX_FILE = DATA_DIR / "grid_geo_index.npz"

_COUNTRY_HU = {
  "DE": "Németország",
  "IT": "Olaszország",
  "HU": "Magyarország",
  "AT": "Ausztria",
  "SK": "Szlovákia",
  "RO": "Románia",
  "HR": "Horvátország",
  "SI": "Szlovénia",
  "CZ": "Csehország",
  "PL": "Lengyelország",
  "UA": "Ukrajna",
  "FR": "Franciaország",
  "GB": "Egyesült Királyság",
  "ES": "Spanyolország",
  "NL": "Hollandia",
  "BE": "Belgium",
  "CH": "Svájc",
  "US": "Egyesült Államok",
  "RU": "Oroszország",
  "DK": "Dánia",
  "SE": "Svédország",
  "NO": "Norvégia",
  "FI": "Finnország",
}


@dataclass(frozen=True)
class PlaceHit:
  name: str
  admin1: str
  country: str
  country_hu: str
  distance_km: float
  population: int


def is_callsign(token: str) -> bool:
  t = token.upper().strip("<>")
  if GRID4_RE.match(t):
    return False
  if REPORT_RE.match(t):
    return False
  return _callsign_is_callsign(t)


@lru_cache(maxsize=8192)
def _call_key(call: str) -> str:
  return normalize_callsign(call)


def grid4_upper(grid: str) -> str:
  """4 karakteres Maidenhead négyzet — normalizált, cache-elt."""
  g = (grid or "").strip()
  if not g:
    return ""
  return _grid4_upper_cached(g.upper()[:4])


@lru_cache(maxsize=4096)
def _grid4_upper_cached(g4: str) -> str:
  return g4


def extract_callsigns_from_message(message: str) -> list[str]:
  """FT8 üzenet összes hívójele (CQ/report melletti állomások)."""
  from cw_discover.ft8.decode_meta import message_stripped

  return list(_extract_callsigns_cached(message_stripped(message)))


@lru_cache(maxsize=4096)
def _extract_callsigns_cached(message: str) -> tuple[str, ...]:
  from cw_discover.ft8.decode_meta import _message_upper_cached

  return tuple(p for p in _message_upper_cached(message).split() if is_callsign(p))


def extract_grid_from_message(message: str) -> str | None:
  """FT8 üzenetből 4 karakteres Maidenhead négyzet (ha van)."""
  from cw_discover.ft8.decode_meta import message_stripped

  return _extract_grid_cached(message_stripped(message))


@lru_cache(maxsize=4096)
def _extract_grid_cached(message: str) -> str | None:
  from cw_discover.ft8.decode_meta import _message_upper_cached

  for part in reversed(_message_upper_cached(message).split()):
    token = part.strip("<>")
    if REPORT_RE.match(token) or is_callsign(token):
      continue
    if GRID4_RE.match(token):
      return token
    if len(token) >= 6 and GRID4_RE.match(token[:4]) and token[4:6].isalpha():
      return token[:4]
  return None


def grid_bounds_deg(grid: str) -> tuple[float, float, float, float]:
  g = grid4_upper(grid)
  lon = (ord(g[0]) - ord("A")) * 20 - 180
  lat = (ord(g[1]) - ord("A")) * 10 - 90
  lon += int(g[2]) * 2
  lat += int(g[3]) * 1
  return lat, lat + 1.0, lon, lon + 2.0


def grid_centre_deg(grid: str) -> tuple[float, float]:
  return _grid_centre_cached(grid4_upper(grid))


@lru_cache(maxsize=4096)
def _grid_centre_cached(g4: str) -> tuple[float, float]:
  return grid_to_latlong(g4)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
  return _haversine_km_cached(
    round(lat1, 2), round(lon1, 2), round(lat2, 2), round(lon2, 2)
  )


@lru_cache(maxsize=8192)
def _haversine_km_cached(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
  r = 6371.0
  p1, p2 = np.radians(lat1), np.radians(lat2)
  dlat = np.radians(lat2 - lat1)
  dlon = np.radians(lon2 - lon1)
  a = np.sin(dlat / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlon / 2) ** 2
  return float(2 * r * np.arcsin(np.sqrt(a)))


def geo_metrics_for_grid(
  grid: str, home_lat: float, home_lon: float
) -> tuple[float | None, float | None]:
  """Távolság + azimut ismert gridből — egy grid_centre passz."""
  _lat, _lon, dist, az = station_geo_for_grid(grid, home_lat, home_lon)
  return dist, az


def geo_metrics_for_g4(
  g4: str, home_lat: float, home_lon: float
) -> tuple[float | None, float | None]:
  """Normalizált g4 — grid4_upper nélkül."""
  _lat, _lon, dist, az = station_geo_for_g4(g4, home_lat, home_lon)
  return dist, az


def station_geo_for_grid(
  grid: str, home_lat: float, home_lon: float
) -> tuple[float, float, float | None, float | None]:
  """lat, lon, distance_km, azimuth — egy grid_centre passz."""
  g4 = grid4_upper(grid)
  if not g4 or not GRID4_RE.match(g4):
    return 0.0, 0.0, None, None
  return _station_geo_for_grid_cached(g4, round(home_lat, 2), round(home_lon, 2))


def station_geo_for_g4(
  g4: str, home_lat: float, home_lon: float
) -> tuple[float, float, float | None, float | None]:
  """Normalizált g4 — grid4_upper nélkül."""
  if not g4 or not GRID4_RE.match(g4):
    return 0.0, 0.0, None, None
  return _station_geo_for_grid_cached(g4, round(home_lat, 2), round(home_lon, 2))


@lru_cache(maxsize=4096)
def _station_geo_for_grid_cached(
  g4: str, home_lat: float, home_lon: float
) -> tuple[float, float, float | None, float | None]:
  try:
    lat, lon = grid_centre_deg(g4)
  except Exception:
    return 0.0, 0.0, None, None
  from cw_discover.ft8.decode_meta import bearing_deg

  return (
    lat,
    lon,
    round(_haversine_km(home_lat, home_lon, lat, lon), 1),
    round(bearing_deg(home_lat, home_lon, lat, lon), 1),
  )


def station_dist_for_g4(g4: str, home_lat: float, home_lon: float) -> float | None:
  """Távolság normalizált 4-char gridből — grid4_upper nélkül."""
  if not g4 or not GRID4_RE.match(g4):
    return None
  _lat, _lon, dist, _az = _station_geo_for_grid_cached(g4, round(home_lat, 2), round(home_lon, 2))
  return dist


def distance_km_for_grid(grid: str, home_lat: float, home_lon: float) -> float | None:
  """Távolság ismert gridből — üzenet parse nélkül."""
  return station_dist_for_g4(grid4_upper(grid), home_lat, home_lon)


def _download_text(url: str) -> str:
  with urlopen(url, timeout=60) as resp:
    return resp.read().decode("utf-8", errors="replace")


def _load_admin1() -> dict[str, str]:
  text = _download_text(ADMIN1_URL)
  out: dict[str, str] = {}
  for line in text.splitlines():
    if not line or line.startswith("#"):
      continue
    parts = line.split("\t")
    if len(parts) >= 2:
      out[parts[0]] = parts[1]
  return out


def _load_countries() -> dict[str, str]:
  text = _download_text(COUNTRY_URL)
  out: dict[str, str] = {}
  for line in text.splitlines():
    if not line or line.startswith("#"):
      continue
    parts = line.split("\t")
    if len(parts) >= 5:
      out[parts[0]] = parts[4]
  return out


def build_index(dest: Path = INDEX_FILE) -> Path:
  dest.parent.mkdir(parents=True, exist_ok=True)
  admin1 = _load_admin1()
  countries = _load_countries()

  with urlopen(CITIES_URL, timeout=120) as resp:
    zdata = resp.read()
  with zipfile.ZipFile(io.BytesIO(zdata)) as zf:
    name = next(n for n in zf.namelist() if n.endswith(".txt"))
    raw = zf.read(name).decode("utf-8", errors="replace")

  names: list[str] = []
  admin1_names: list[str] = []
  countries_list: list[str] = []
  ccs: list[str] = []
  lats: list[float] = []
  lons: list[float] = []
  pops: list[int] = []

  for line in raw.splitlines():
    p = line.split("\t")
    if len(p) < 15:
      continue
    lat, lon = float(p[4]), float(p[5])
    cc = p[8]
    a1 = admin1.get(f"{cc}.{p[10]}", p[10])
    names.append(p[1])
    admin1_names.append(a1)
    countries_list.append(countries.get(cc, cc))
    ccs.append(cc)
    lats.append(lat)
    lons.append(lon)
    pops.append(int(p[14]) if p[14] else 0)

  np.savez_compressed(
    dest,
    lat=np.array(lats, dtype=np.float64),
    lon=np.array(lons, dtype=np.float64),
    name=np.array(names, dtype=object),
    admin1=np.array(admin1_names, dtype=object),
    country=np.array(countries_list, dtype=object),
    cc=np.array(ccs, dtype=object),
    pop=np.array(pops, dtype=np.int32),
  )
  return dest


@dataclass
class GeoDisplayOptions:
  show_city_km: bool = False
  show_home_km: bool = True
  home: HomeQth | None = None


class GridGeoLookup:
  """Legközelebbi város + hívójel→lokátor munkamenet-cache."""

  def __init__(self) -> None:
    self._tree: cKDTree | None = None
    self._meta: dict[str, np.ndarray] | None = None
    self._ready = False
    self._call_grid: dict[str, str] = {}
    self._cache_lock = threading.Lock()
    self.display = GeoDisplayOptions()

  def ensure_ready(self) -> None:
    if self._ready:
      return
    if not INDEX_FILE.exists():
      build_index(INDEX_FILE)
    data = np.load(INDEX_FILE, allow_pickle=True)
    pts = np.column_stack([data["lat"], data["lon"]])
    self._tree = cKDTree(pts)
    self._meta = {
      "name": data["name"],
      "admin1": data["admin1"],
      "country": data["country"],
      "cc": data["cc"],
      "pop": data["pop"],
      "lat": data["lat"],
      "lon": data["lon"],
    }
    self._ready = True

  def remember_callsigns(self, message: str, grid: str, calls: list[str] | None = None) -> None:
    """CQ / standard üzenetből hívójel→lokátor mentés."""
    from cw_discover.ft8.decode_meta import message_upper

    parts = message_upper(message).split()
    g = grid4_upper(grid)
    with self._cache_lock:
      if parts and parts[0] == "CQ":
        idx = 2 if len(parts) > 3 and parts[1] == "DX" else 1
        if idx < len(parts) and is_callsign(parts[idx]):
          self._call_grid[parts[idx]] = g
        return
      if calls is None:
        from cw_discover.ft8.decode_meta import message_stripped

        calls = list(_extract_callsigns_cached(message_stripped(message)))
      if len(calls) >= 2:
        self._call_grid[calls[1]] = g
      elif len(calls) == 1:
        self._call_grid[calls[0]] = g

  def grid_for_call(self, call: str) -> str | None:
    with self._cache_lock:
      return self._call_grid.get(_call_key(call))

  def grid_from_callsigns(self, message: str) -> tuple[str | None, str | None]:
    """Jelentés/RR73 üzenet — korábban hallott hívójel lokátora."""
    from cw_discover.ft8.decode_meta import message_stripped

    calls = _extract_callsigns_cached(message_stripped(message))
    with self._cache_lock:
      for call in reversed(calls):
        if call in self._call_grid:
          return self._call_grid[call], call
    return None, None

  def nearest_place(self, lat: float, lon: float) -> PlaceHit:
    self.ensure_ready()
    assert self._tree is not None and self._meta is not None
    _dist, idx = self._tree.query([lat, lon])
    i = int(idx)
    plat = float(self._meta["lat"][i])
    plon = float(self._meta["lon"][i])
    cc = str(self._meta["cc"][i])
    return PlaceHit(
      name=str(self._meta["name"][i]),
      admin1=str(self._meta["admin1"][i]),
      country=str(self._meta["country"][i]),
      country_hu=_COUNTRY_HU.get(cc, str(self._meta["country"][i])),
      distance_km=_haversine_km(lat, lon, plat, plon),
      population=int(self._meta["pop"][i]),
    )

  def format_grid_description(self, grid: str, lat_c: float, lon_c: float, place: PlaceHit) -> str:
    g = grid4_upper(grid)
    region = place.admin1 if place.admin1 and place.admin1 != place.name else ""
    where = place.name if not region else f"{place.name}, {region}"
    tail_parts: list[str] = []
    if self.display.show_city_km:
      tail_parts.append(f"{place.distance_km:.0f} km a négyzet közepétől")
    if self.display.show_home_km and self.display.home is not None:
      d_home = _haversine_km(lat_c, lon_c, self.display.home.lat, self.display.home.lon)
      tail_parts.append(f"{d_home:.0f} km {self.display.home.name}tól")
    tail_parts.append(f"{lat_c:.2f}°É {lon_c:.2f}°K")
    tail = ", ".join(tail_parts)
    return f"{place.country_hu} — {where} — {g} ({tail})"

  def _place_for_grid(self, grid: str) -> tuple[float, float, PlaceHit]:
    return self._place_for_grid_cached(grid4_upper(grid))

  @lru_cache(maxsize=4096)
  def _place_for_grid_cached(self, g4: str) -> tuple[float, float, PlaceHit]:
    lat_c, lon_c = grid_centre_deg(g4)
    return lat_c, lon_c, self.nearest_place(lat_c, lon_c)

  def describe_grid(self, grid: str) -> str:
    return _describe_grid_text(grid)

  def clear_place_cache(self) -> None:
    self._place_for_grid_cached.cache_clear()
    _grid_centre_cached.cache_clear()
    _grid4_upper_cached.cache_clear()
    _station_geo_for_grid_cached.cache_clear()
    _describe_grid_text.cache_clear()
    _describe_message_cached.cache_clear()

  def describe_message(self, message: str) -> str:
    from cw_discover.ft8.decode_meta import message_stripped

    m = message_stripped(message)
    grid = _extract_grid_cached(m)
    if grid:
      self.remember_callsigns(m, grid)
    return _describe_message_cached(m)


@lru_cache(maxsize=2048)
def _describe_grid_text(grid: str) -> str:
  g = grid4_upper(grid)
  if not GRID4_RE.match(g):
    return ""
  lat_c, lon_c, place = lookup._place_for_grid(g)
  return lookup.format_grid_description(g, lat_c, lon_c, place)


@lru_cache(maxsize=2048)
def _describe_message_cached(message: str) -> str:
  grid = _extract_grid_cached(message)
  via_call: str | None = None
  if not grid:
    grid, via_call = lookup.grid_from_callsigns(message)
  if not grid:
    return "—"
  text = _describe_grid_text(grid)
  if via_call:
    text = f"{text} [{via_call}]"
  return text


lookup = GridGeoLookup()
