"""Default home QTH — override via station.json / map GUI."""
from __future__ import annotations

from dataclasses import dataclass

from PyFT8.databases import grid_to_latlong

# Example defaults (replace with your QTH in station.json)
HOME_GRID = "FN31"
HOME_NAME = "Example QTH"
HOME_COUNTRY = "United States"
HOME_LAT = 42.0
HOME_LON = -72.0


@dataclass(frozen=True)
class HomeQth:
  name: str
  country: str
  grid: str
  lat: float
  lon: float

  @classmethod
  def default(cls) -> HomeQth:
    glat, glon = grid_to_latlong(HOME_GRID)
    return cls(
      name=HOME_NAME,
      country=HOME_COUNTRY,
      grid=HOME_GRID,
      lat=HOME_LAT,
      lon=HOME_LON,
    )


DEFAULT_HOME = HomeQth.default()
