"""Truck Load Analyzer application package."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("truck-load-analyzer")
except PackageNotFoundError:  # pragma: no cover - only before the package is installed
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
