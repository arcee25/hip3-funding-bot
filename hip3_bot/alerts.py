"""Telegram alerter. Falls back to logging when not configured."""
from __future__ import annotations

import logging

from .config import Config

logger = logging.getLogger(__name__)


class TelegramAlerter:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._bot = None
        if cfg.telegram_bot_token and cfg.telegram_chat_id:
            try:
                from telegram import Bot

                self._bot = Bot(token=cfg.telegram_bot_token)
            except ImportError:
                logger.warning("python-telegram-bot not installed")

    async def send(self, text: str) -> None:
        if not self._bot:
            logger.info("[alert] %s", text)
            return
        try:
            await self._bot.send_message(
                chat_id=self.cfg.telegram_chat_id,
                text=text,
                parse_mode="Markdown",
            )
        except Exception:
            logger.exception("telegram send failed; text=%s", text)
