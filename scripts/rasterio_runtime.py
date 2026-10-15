"""Point a frozen Rasterio wheel at its bundled GDAL and PROJ databases."""
import os
from pathlib import Path
import sys


if getattr(sys, "frozen", False):
    bundle = Path(sys._MEIPASS)
    for variable, folder in (("GDAL_DATA", "gdal_data"), ("PROJ_DATA", "proj_data")):
        location = bundle / "rasterio" / folder
        if location.is_dir():
            os.environ[variable] = str(location)
    if "PROJ_DATA" in os.environ:
        os.environ["PROJ_LIB"] = os.environ["PROJ_DATA"]
