"""
Числовой слой: day/month snapshots, кэш Redis,
использует ключи из sheets_meta.py.
"""
from __future__ import annotations
import os
import json
import asyncio
import logging
from typing import Callable, Any

from .gs_utils import open_worksheet
from .sheets_meta import SheetMeta

import redis.asyncio as aioredis

log = logging.getLogger(__name__)


class SheetNumeric:
    def __init__(self) -> None:
        self.ws, self.rows = open_worksheet()
        self.meta = SheetMeta().build_meta()
        self.redis = aioredis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            encoding="utf-8", decode_responses=True
        )

    async def _cached(self, key: str, ttl: int, producer: Callable[[], Any]) -> Any:
        if (val := await self.redis.get(key)):
            return json.loads(val)
        data = producer()
        await self.redis.set(key, json.dumps(data), ex=ttl)
        return data

    def _cell(self, row: int, col: int) -> float:
        raw = self.ws.cell((row, col)).value or ""
        cleaned = raw.replace("\xa0", "").replace(" ", "").replace(",", ".").replace("₽", "").strip()
        try:
            return float(cleaned) if cleaned else 0.0
        except ValueError:
            return 0.0

    def _day_snapshot_sync(self, date: str) -> dict[str, float]:
        col = self.meta["date_cols"].get(date)
        if col is None:
            raise ValueError(f"Date {date} not found in metadata")

        out = {"income": 0.0, "expense": 0.0}
        # income
        for cat in self.meta["income"]["П"]["cats"].values():
            out["income"] += self._cell(cat["row"], col)
            for sub in cat["subs"].values():
                out["income"] += self._cell(sub["row"], col)

        # expense
        for sec in self.meta["expenses"].values():
            for cat in sec["cats"].values():
                out["expense"] += self._cell(cat["row"], col)
                for sub in cat["subs"].values():
                    out["expense"] += self._cell(sub["row"], col)

        return out

    async def day_snapshot(self, date: str) -> dict[str, float]:
        return await self._cached(f"day:{date}", 300, lambda: self._day_snapshot_sync(date))

    def month_balances(self, ym: str) -> dict[str, float]:
        cols = self.meta["month_cols"].get(ym)
        if not cols:
            raise ValueError(f"Month {ym} not in metadata")
        return {
            "balance": self._cell(2, cols["balance"]),
            "free_cash": self._cell(3, cols["free"]),
        }

    def _month_snapshot_sync(self, ym: str) -> dict[str, float]:
        cols = self.meta["month_cols"][ym]
        inc = sum(
            self._cell(cat["row"], cols["balance"])
            for cat in self.meta["income"]["П"]["cats"].values()
        )
        exp = sum(
            self._cell(sub["row"], cols["balance"])
            for sec in self.meta["expenses"].values()
            for cat in sec["cats"].values()
            for sub in [{"row": cat["row"]}] + list(cat["subs"].values())
        )
        return {"income": inc, "expense": exp}

    async def months_overview(self) -> dict[str, dict[str, float]]:
        def producer():
            out: dict[str, dict[str, float]] = {}
            for ym in self.meta["month_cols"]:
                data = self.month_balances(ym)
                data.update(self._month_snapshot_sync(ym))
                out[ym] = data
            return out

        return await self._cached("months:overview", 3600, producer)

    async def _warm_cache(self) -> None:
        # пример прогрева
        await self.day_snapshot(list(self.meta["date_cols"].keys())[0])
        await self.months_overview()


if __name__ == "__main__":
    import pprint

    sn = SheetNumeric()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(sn._warm_cache())
    # проверка
    first = list(sn.meta["date_cols"].keys())[0]
    print("▶ Day", first, "→", loop.run_until_complete(sn.day_snapshot(first)))
    pprint.pprint(loop.run_until_complete(sn.months_overview()), width=120)
    loop.close()
