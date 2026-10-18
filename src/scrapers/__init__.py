"""Scraper registry: name -> BaseScraper subclass. The kariyernet scraper is added later."""
from __future__ import annotations

from .base import BaseScraper

SCRAPERS: dict[str, type[BaseScraper]] = {}

__all__ = ["BaseScraper", "SCRAPERS"]
