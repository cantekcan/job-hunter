"""Scraper registry: name -> BaseScraper subclass."""
from __future__ import annotations

from .base import BaseScraper
from .kariyernet import KariyerNetScraper

SCRAPERS: dict[str, type[BaseScraper]] = {
    KariyerNetScraper.name: KariyerNetScraper,
}

__all__ = ["BaseScraper", "KariyerNetScraper", "SCRAPERS"]
