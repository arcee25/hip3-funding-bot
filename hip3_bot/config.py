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
    # Mode
    mode: str  # "scanner" | "paper" | "live"

    # Hyperliquid
    hl_private_key: str | None
    hl_account_address: str | None
    hl_api_url: str
    hl_use_testnet: bool

    # Ostium (Arbitrum)
    ostium_rpc_url: str
    ostium_private_key: str | None
    ostium_account_address: str | None
    ostium_router_address: str
    ostium_use_testnet: bool

    # Telegram
    telegram_bot_token: str | None
    telegram_chat_id: str | None

    # Bot
    db_path: Path
    log_level: str
    scan_interval_sec: int

    # Strategy thresholds
    min_entry_apr_pct: float
    max_position_pct: float
    kelly_fraction: float
    round_trip_fee_bps: float
    hl_round_trip_bps: float
    ostium_round_trip_bps: float
    min_book_depth_usd: float
    long_skew_threshold: float
    consecutive_positive_funding: int
    delta_drift_threshold: float
    exit_apr_pct: float
    rebalance_interval_min: int
    deployer_poll_sec: int

    # v1.1 thresholds
    min_ostium_lp_usd: float
    max_basis_pct: float
    ostium_hostile_funding_ratio: float
    ostium_max_slippage_bps: float

    @classmethod
    def from_env(cls) -> "Config":
        mode = (_env("MODE", "scanner") or "scanner").lower()
        if mode not in {"scanner", "paper", "live"}:
            raise RuntimeError(
                f"MODE must be scanner|paper|live, got {mode!r}"
            )
        return cls(
            mode=mode,
            hl_private_key=_env("HL_PRIVATE_KEY"),
            hl_account_address=_env("HL_ACCOUNT_ADDRESS"),
            hl_api_url=_env("HL_API_URL", "https://api.hyperliquid.xyz"),
            hl_use_testnet=_env_bool("HL_USE_TESTNET", mode != "live"),
            ostium_rpc_url=_env(
                "OSTIUM_RPC_URL",
                "https://arb1.arbitrum.io/rpc"
                if mode == "live"
                else "https://sepolia-rollup.arbitrum.io/rpc",
            ),
            ostium_private_key=_env("OSTIUM_PRIVATE_KEY"),
            ostium_account_address=_env("OSTIUM_ACCOUNT_ADDRESS"),
            ostium_router_address=_env(
                "OSTIUM_ROUTER_ADDRESS",
                "0x0000000000000000000000000000000000000000",
            ),
            ostium_use_testnet=_env_bool("OSTIUM_USE_TESTNET", mode != "live"),
            telegram_bot_token=_env("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=_env("TELEGRAM_CHAT_ID"),
            db_path=Path(_env("DB_PATH", "./hip3_bot.db")),
            log_level=_env("LOG_LEVEL", "INFO"),
            scan_interval_sec=_env_int("SCAN_INTERVAL_SEC", 30),
            min_entry_apr_pct=_env_float("MIN_ENTRY_APR_PCT", 20.0),
            max_position_pct=_env_float("MAX_POSITION_PCT", 0.10),
            kelly_fraction=_env_float("KELLY_FRACTION", 0.25),
            round_trip_fee_bps=_env_float("ROUND_TRIP_FEE_BPS", 28.0),
            hl_round_trip_bps=_env_float("HL_ROUND_TRIP_BPS", 18.0),
            ostium_round_trip_bps=_env_float("OSTIUM_ROUND_TRIP_BPS", 10.0),
            min_book_depth_usd=_env_float("MIN_BOOK_DEPTH_USD", 50_000.0),
            long_skew_threshold=_env_float("LONG_SKEW_THRESHOLD", 0.60),
            consecutive_positive_funding=_env_int(
                "CONSECUTIVE_POSITIVE_FUNDING", 3
            ),
            delta_drift_threshold=_env_float("DELTA_DRIFT_THRESHOLD", 0.05),
            exit_apr_pct=_env_float("EXIT_APR_PCT", 10.0),
            rebalance_interval_min=_env_int("REBALANCE_INTERVAL_MIN", 15),
            deployer_poll_sec=_env_int("DEPLOYER_POLL_SEC", 5),
            min_ostium_lp_usd=_env_float("MIN_OSTIUM_LP_USD", 50_000.0),
            max_basis_pct=_env_float("MAX_BASIS_PCT", 0.005),
            ostium_hostile_funding_ratio=_env_float(
                "OSTIUM_HOSTILE_FUNDING_RATIO", 0.50
            ),
            ostium_max_slippage_bps=_env_float(
                "OSTIUM_MAX_SLIPPAGE_BPS", 30.0
            ),
        )

    @property
    def is_dry_run(self) -> bool:
        """scanner and paper modes never touch live mainnet capital."""
        return self.mode in ("scanner", "paper")
