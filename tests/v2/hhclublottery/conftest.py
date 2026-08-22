# -*- coding: utf-8 -*-
"""hhclublottery 的测试夹具。MoviePilot 主程序桩件见 mp_stubs.py。"""
import sys
from pathlib import Path

import pytest

# 桩件、假站点和抽奖核心都在这两个目录下
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "plugins.v2" / "hhclublottery"))

from mp_stubs import HH  # noqa: E402


@pytest.fixture
def plugin():
    """一个初始化过的插件实例，配置全走类默认值。"""
    instance = HH.HHClubLottery()
    instance.init_plugin({})
    return instance


@pytest.fixture
def instant(monkeypatch):
    """把抽奖间隔抹平，测行为不测墙上时钟。"""
    monkeypatch.setattr(HH.LotteryRunner, "sleep",
                        lambda self, ms: self.stop_event.is_set())
