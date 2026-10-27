"""Companies House lookups for supplier identity.

Live mode: the public Companies House API (search by name; needs COMPANIES_HOUSE_API_KEY,
rate limit ~600 requests / 5 minutes; a 0.6s gap keeps well under it).
Sample mode: a cached file data/sample/companies_house.json of earlier lookups.
If neither is available the Resolver carries on without it - a match then needs
a human to confirm, which is the honest outcome.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

import httpx


class CompaniesHouseClient:
    def __init__(self, api_key: str = "", cache_path: Optional[Path] = None, live: bool = False) -> None:
        self.api_key = api_key
        self.live = live and bool(api_key)
        self.cache_path = cache_path
        self.cache: dict[str, Any] = {}
        if cache_path and cache_path.exists():
            self.cache = json.loads(cache_path.read_text(encoding="utf-8"))
        self._client = httpx.Client(timeout=20.0) if self.live else None
        self._last = 0.0

    @property
    def available(self) -> bool:
        return self.live or bool(self.cache)

    def search(self, name: str) -> Optional[dict[str, Any]]:
        key = name.strip().upper()
        if key in self.cache:
            return self.cache[key]
        if not self.live:
            return None
        gap = 0.6 - (time.time() - self._last)
        if gap > 0:
            time.sleep(gap)
        self._last = time.time()
        r = self._client.get(
            "https://api.company-information.service.gov.uk/search/companies",
            params={"q": name, "items_per_page": 3},
            auth=(self.api_key, ""),
        )
        if r.status_code != 200:
            return None
        items = r.json().get("items") or []
        hit = None
        if items:
            top = items[0]
            hit = {
                "company_number": top.get("company_number"),
                "title": top.get("title"),
                "status": top.get("company_status"),
                "address": (top.get("address_snippet") or "")[:120],
            }
        self.cache[key] = hit
        if self.cache_path:
            self.cache_path.write_text(json.dumps(self.cache, indent=1, sort_keys=True), encoding="utf-8")
        return hit
