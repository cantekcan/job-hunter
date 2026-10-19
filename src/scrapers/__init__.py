"""Scraper registry: name -> BaseScraper subclass. Job.source is always the scraper name."""
from __future__ import annotations

from .base import BaseScraper, SourceBlocked
from .indeed import IndeedScraper
from .kariyernet import KariyerNetScraper
from .linkedin import LinkedInScraper
from .secretcv import SecretcvScraper
from .yenibiris import YenibirisScraper

SCRAPERS: dict[str, type[BaseScraper]] = {
    cls.name: cls
    for cls in (KariyerNetScraper, LinkedInScraper, IndeedScraper, SecretcvScraper, YenibirisScraper)
}

__all__ = ["BaseScraper", "SourceBlocked", "SCRAPERS", "KariyerNetScraper", "LinkedInScraper",
           "IndeedScraper", "SecretcvScraper", "YenibirisScraper"]
