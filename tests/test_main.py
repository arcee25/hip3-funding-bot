from __future__ import annotations

import pytest

from hip3_bot.main import require_confirm_live


def test_require_confirm_live_passes_for_scanner():
    require_confirm_live("scanner", confirm=False)


def test_require_confirm_live_passes_for_paper():
    require_confirm_live("paper", confirm=False)


def test_require_confirm_live_fails_without_flag():
    with pytest.raises(SystemExit):
        require_confirm_live("live", confirm=False)


def test_require_confirm_live_passes_with_flag():
    require_confirm_live("live", confirm=True)
