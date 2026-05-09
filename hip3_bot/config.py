"""Environment-driven configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def _env(key: str, default: str | None = None) -> str | None:
    val = os.getenv(key)
    if val is None or val == "":
        return default
    return val


def _env_required(key: str) -> str:
    val = _env(key)
    if val is None:
        raise RuntimeError(f"Missing required env var: {key}")
    return val


def _env_bool(key: str, default: bool = False) -> bool:
    val = _env(key)
    if val is None:
        return default
    return val.lower() in ("1", "true", "yes", "on")


def _env_int(key: str, default: int) -> int:
    val = _env(key)
    return int(val) if val else default


def _env_float(key: str, default: float) -> float:
    val = _env(key)
    return float(val) if val else default


@dataclass(frozen=True)
class Config:
    hl_private_key: str | None
    hl_account_address: str | None
    hl_api_url: str
    hl_use_testnet: bool

    ibkr_host: str
    ibkr_port: int
    ibkr_client_id: int

    telegram_bot_token: str | None
    telegram_chat_id: str | None

    db_path: Path
    log_level: str
    scan_interval_sec: int
    dry_run: bool
    hedge_venue: str

    min_entry_apr_pct: float
    max_position_pct: float
    kelly_fraction: float
    round_trip_fee_bps: float
    min_book_depth_usd: float
    long_skew_threshold: float
    consecutive_positive_funding: int
    delta_drift_threshold: float
    exit_apr_pct: float
    rebalance_interval_min: int
    deployer_poll_sec: int

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            hl_private_key=_env("HL_PRIVATE_KEY"),
            hl_account_address=_env("HL_ACCOUNT_ADDRESS"),
            hl_api_url=_env("HL_API_URL", "https://api.hyperliquid.xyz"),
            hl_use_testnet=_env_bool("HL_USE_TESTNET", True),
            ibkr_host=_env("IBKR_HOST", "127.0.0.1"),
            ibkr_port=_env_int("IBKR_PORT", 7497),
            ibkr_client_id=_env_int("IBKR_CLIENT_ID", 1),
            telegram_bot_token=_env("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=_env("TELEGRAM_CHAT_ID"),
            db_path=Path(_env("DB_PATH", "./hip3_bot.db")),
            log_level=_env("LOG_LEVEL", "INFO"),
            scan_interval_sec=_env_int("SCAN_INTERVAL_SEC", 30),
            dry_run=_env_bool("DRY_RUN", True),
            hedge_venue=_env("HEDGE_VENUE", "paper"),
            min_entry_apr_pct=_env_float("MIN_ENTRY_APR_PCT", 20.0),
            max_position_pct=_env_float("MAX_POSITION_PCT", 0.10),
            kelly_fraction=_env_float("KELLY_FRACTION", 0.25),
            round_trip_fee_bps=_env_float("ROUND_TRIP_FEE_BPS", 18.0),
            min_book_depth_usd=_env_float("MIN_BOOK_DEPTH_USD", 50_000.0),
            long_skew_threshold=_env_float("LONG_SKEW_THRESHOLD", 0.60),
            consecutive_positive_funding=_env_int(
                "CONSECUTIVE_POSITIVE_FUNDING", 3
            ),
            delta_drift_threshold=_env_float("DELTA_DRIFT_THRESHOLD", 0.05),
            exit_apr_pct=_env_float("EXIT_APR_PCT", 10.0),
            rebalance_interval_min=_env_int("REBALANCE_INTERVAL_MIN", 15),
            deployer_poll_sec=_env_int("DEPLOYER_POLL_SEC", 5),
        )
