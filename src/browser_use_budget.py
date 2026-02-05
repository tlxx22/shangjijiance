from __future__ import annotations

import json
import os
import sqlite3
import contextlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from zoneinfo import ZoneInfo

from browser_use.llm.base import BaseChatModel
from browser_use.tokens.service import TokenCost

from .logger_config import get_logger

logger = get_logger()


class BudgetExceededError(RuntimeError):
	"""Raised when the daily browser-use budget is exceeded."""


@dataclass(frozen=True)
class BudgetStatus:
	day: str
	limit_usd: float
	spent_usd: float
	stopped: bool


def _repo_root() -> Path:
	return Path(__file__).resolve().parents[1]


def _get_tz() -> ZoneInfo | None:
	tz_name = (os.getenv("BROWSER_USE_BUDGET_TZ") or "Asia/Shanghai").strip()
	try:
		return ZoneInfo(tz_name)
	except Exception:
		return None


def _today_key() -> str:
	tz = _get_tz()
	now = datetime.now(tz) if tz else datetime.now()
	return now.date().isoformat()


class DailyBudgetStore:
	"""
	SQLite-based daily budget accumulator (cross-process safe).

	Schema:
	- day: YYYY-MM-DD
	- spent_usd: cumulative cost in USD
	- stopped: 0/1
	"""

	def __init__(self, db_path: Path):
		self._db_path = Path(db_path)
		self._conn: sqlite3.Connection | None = None
		self._schema_ready = False

	def _connect(self) -> sqlite3.Connection:
		if self._conn is not None:
			return self._conn

		self._db_path.parent.mkdir(parents=True, exist_ok=True)
		conn = sqlite3.connect(self._db_path, timeout=30, isolation_level=None)
		conn.execute("PRAGMA journal_mode=WAL;")
		conn.execute("PRAGMA synchronous=NORMAL;")
		conn.execute("PRAGMA busy_timeout=5000;")
		self._conn = conn
		return conn

	def _ensure_schema(self) -> None:
		if self._schema_ready:
			return
		conn = self._connect()
		conn.execute(
			"""
			CREATE TABLE IF NOT EXISTS browser_use_daily_budget (
				day TEXT PRIMARY KEY,
				spent_usd REAL NOT NULL DEFAULT 0.0,
				stopped INTEGER NOT NULL DEFAULT 0,
				updated_at TEXT NOT NULL
			)
			""".strip()
		)
		self._schema_ready = True

	def get_status(self, *, day: str, limit_usd: float) -> BudgetStatus:
		self._ensure_schema()
		conn = self._connect()
		row = conn.execute(
			"SELECT spent_usd, stopped FROM browser_use_daily_budget WHERE day = ?",
			(day,),
		).fetchone()

		if row is None:
			now = datetime.now().isoformat(timespec="seconds")
			conn.execute(
				"INSERT OR IGNORE INTO browser_use_daily_budget(day, spent_usd, stopped, updated_at) VALUES (?, 0.0, 0, ?)",
				(day, now),
			)
			return BudgetStatus(day=day, limit_usd=limit_usd, spent_usd=0.0, stopped=False)

		spent = float(row[0] or 0.0)
		stopped = bool(row[1]) or (limit_usd > 0 and spent >= limit_usd)
		return BudgetStatus(day=day, limit_usd=limit_usd, spent_usd=spent, stopped=stopped)

	def add_cost(self, *, day: str, delta_usd: float, limit_usd: float) -> BudgetStatus:
		"""
		Atomically add cost for the day and update stop flag if threshold exceeded.
		"""
		self._ensure_schema()
		conn = self._connect()
		now = datetime.now().isoformat(timespec="seconds")

		try:
			conn.execute("BEGIN IMMEDIATE")
			conn.execute(
				"INSERT OR IGNORE INTO browser_use_daily_budget(day, spent_usd, stopped, updated_at) VALUES (?, 0.0, 0, ?)",
				(day, now),
			)
			if delta_usd > 0:
				conn.execute(
					"""
					UPDATE browser_use_daily_budget
					SET spent_usd = spent_usd + ?,
					    stopped = CASE WHEN (spent_usd + ?) >= ? THEN 1 ELSE stopped END,
					    updated_at = ?
					WHERE day = ?
					""".strip(),
					(delta_usd, delta_usd, float(limit_usd), now, day),
				)
			else:
				# Ensure stop flag consistent even if delta=0.
				conn.execute(
					"""
					UPDATE browser_use_daily_budget
					SET stopped = CASE WHEN spent_usd >= ? THEN 1 ELSE stopped END,
					    updated_at = ?
					WHERE day = ?
					""".strip(),
					(float(limit_usd), now, day),
				)

			row = conn.execute(
				"SELECT spent_usd, stopped FROM browser_use_daily_budget WHERE day = ?",
				(day,),
			).fetchone()
			conn.execute("COMMIT")
		except Exception:
			with contextlib.suppress(Exception):
				conn.execute("ROLLBACK")
			raise

		spent = float(row[0] or 0.0) if row else 0.0
		stopped = bool(row[1]) if row else False
		return BudgetStatus(day=day, limit_usd=limit_usd, spent_usd=spent, stopped=stopped)


def _default_pricing_path() -> Path:
	return Path(os.getenv("BROWSER_USE_PRICING_DATA_PATH") or (_repo_root() / "pricing" / "token_cost_pricing.json"))


def _load_pricing_data(path: Path) -> dict[str, Any]:
	"""
	Load pricing mapping used by browser_use.tokens.service.TokenCost.

	Supported formats:
	- Plain mapping: {"model": {...}, ...}
	- CachedPricingData-like wrapper: {"timestamp": "...", "data": {...}}
	"""
	p = Path(path)
	raw = json.loads(p.read_text(encoding="utf-8"))
	if isinstance(raw, dict) and "data" in raw and isinstance(raw["data"], dict):
		return raw["data"]
	if not isinstance(raw, dict):
		raise ValueError(f"Invalid pricing json type: {type(raw).__name__}")
	return raw


def build_token_cost_from_local_pricing(pricing_path: Path | None = None) -> TokenCost:
	"""
	Build TokenCost service WITHOUT network fetch by injecting pricing data from local file.
	"""
	path = pricing_path or _default_pricing_path()
	data = _load_pricing_data(path)

	service = TokenCost(include_cost=True)
	# Inject and mark initialized to avoid remote fetch.
	service._pricing_data = data  # type: ignore[attr-defined]
	service._initialized = True  # type: ignore[attr-defined]
	service.include_cost = True
	return service


class BrowserUseBudget:
	def __init__(
		self,
		*,
		limit_usd: float = 50.0,
		db_path: Path | None = None,
		pricing_path: Path | None = None,
	):
		self.limit_usd = float(limit_usd)
		self.store = DailyBudgetStore(db_path or (Path("output") / "browser_use_budget.sqlite"))
		self.token_cost = build_token_cost_from_local_pricing(pricing_path)

	def status(self) -> BudgetStatus:
		day = _today_key()
		return self.store.get_status(day=day, limit_usd=self.limit_usd)

	def is_stopped(self) -> bool:
		return self.status().stopped

	def add_cost(self, delta_usd: float) -> BudgetStatus:
		day = _today_key()
		return self.store.add_cost(day=day, delta_usd=float(delta_usd), limit_usd=self.limit_usd)

	def wrap_llm(self, llm: BaseChatModel) -> BaseChatModel:
		"""
		Wrap llm.ainvoke() to:
		- pre-check global stop flag (cross-process)
		- compute cost from usage (missing usage => cost=0)
		- atomically accumulate cost and set stop flag when exceeding limit
		"""
		if getattr(llm, "_browser_use_budget_wrapped", False):
			return llm

		original_ainvoke = llm.ainvoke
		budget = self

		async def tracked_ainvoke(messages, output_format=None, **kwargs):
			# Stop fast before making a paid call (except in-flight calls in other workers).
			if budget.is_stopped():
				st = budget.status()
				raise BudgetExceededError(
					f"browser-use daily budget exceeded: spent=${st.spent_usd:.4f}, limit=${st.limit_usd:.2f}"
				)

			result = await original_ainvoke(messages, output_format, **kwargs)

			usage = getattr(result, "usage", None)
			delta = 0.0
			if usage is not None:
				try:
					cost = await budget.token_cost.calculate_cost(llm.model, usage)
					delta = float(cost.total_cost) if cost is not None else 0.0
				except Exception:
					# Caller required: usage missing/invalid => treat as 0.
					delta = 0.0

			st = budget.add_cost(delta)
			if st.stopped:
				logger.warning(
					f"[Budget] browser-use daily budget reached: spent=${st.spent_usd:.4f} / ${st.limit_usd:.2f}"
				)

			return result

		setattr(llm, "ainvoke", tracked_ainvoke)
		setattr(llm, "_browser_use_budget_wrapped", True)
		return llm


_BUDGET_SINGLETON: BrowserUseBudget | None = None


def get_budget() -> BrowserUseBudget:
	"""
	Process-local singleton accessor.

	Note: state is shared cross-process via SQLite file.
	"""
	global _BUDGET_SINGLETON
	if _BUDGET_SINGLETON is None:
		limit = float(os.getenv("BROWSER_USE_DAILY_BUDGET_USD") or "50")
		db_path = Path(os.getenv("BROWSER_USE_BUDGET_DB_PATH") or (Path("output") / "browser_use_budget.sqlite"))
		pricing_path = Path(os.getenv("BROWSER_USE_PRICING_DATA_PATH") or (_repo_root() / "pricing" / "token_cost_pricing.json"))
		_BUDGET_SINGLETON = BrowserUseBudget(limit_usd=limit, db_path=db_path, pricing_path=pricing_path)
	return _BUDGET_SINGLETON
