# -*- coding: utf-8 -*-
"""
为 plugins.v2/discordmsgforward 提供 MoviePilot 主程序的最小桩实现，
使插件可以脱离 MoviePilot 运行环境被单独导入和测试。
"""
import enum
import importlib.util
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_FILE = REPO_ROOT / "plugins.v2" / "discordmsgforward" / "__init__.py"


# ---------------- MoviePilot 主程序桩 ----------------
class _Settings:
    TZ = "Asia/Shanghai"
    PROXY = None


class _NotificationType(enum.Enum):
    Plugin = "插件通知"
    Manual = "手动处理通知"


class _EventType(enum.Enum):
    PluginAction = "plugin.action"


class _Event:
    def __init__(self, event_data=None):
        self.event_data = event_data or {}


class _EventManager:
    @staticmethod
    def register(_etype):
        def decorator(func):
            return func
        return decorator


class _NotifierConfig:
    def __init__(self, name, enabled=True):
        self.name = name
        self.enabled = enabled


class _NotificationHelper:
    # 由测试替换
    configs = {}

    def get_configs(self):
        return self.configs


class _Logger:
    @staticmethod
    def info(*_a, **_k):
        pass

    @staticmethod
    def warning(*_a, **_k):
        pass

    @staticmethod
    def error(*_a, **_k):
        pass

    @staticmethod
    def debug(*_a, **_k):
        pass


class _PluginBase:
    """最小插件基类：数据读写走内存字典，post_message 记录调用"""

    def __init__(self):
        self._store = {}
        self.sent = []
        self.post_error = None

    def save_data(self, key, value):
        self._store[key] = value

    def get_data(self, key):
        return self._store.get(key)

    def post_message(self, **kwargs):
        if self.post_error:
            raise self.post_error
        self.sent.append(kwargs)


def _install_stubs():
    def module(name, **attrs):
        mod = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(mod, key, value)
        sys.modules[name] = mod
        return mod

    module("app")
    module("app.core")
    module("app.core.config", settings=_Settings())
    module("app.core.event", eventmanager=_EventManager(), Event=_Event)
    module("app.helper")
    module("app.helper.notification", NotificationHelper=_NotificationHelper)
    module("app.plugins", _PluginBase=_PluginBase)
    module("app.log", logger=_Logger())
    module("app.schemas", NotificationType=_NotificationType)
    module("app.schemas.types", EventType=_EventType)


_install_stubs()


def _load_plugin_module():
    spec = importlib.util.spec_from_file_location("dmf_plugin", PLUGIN_FILE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["dmf_plugin"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def dmf():
    """插件模块"""
    return _load_plugin_module()


@pytest.fixture
def plugin(dmf):
    """已初始化的插件实例（Token 已填、无规则）"""
    p = dmf.DiscordMsgForward()
    p.init_plugin({"enabled": True, "token": "fake-token", "interval": 5, "history_days": 30})
    # init_plugin 会起一个后台刷新任务，测试里不需要
    p.stop_service()
    return p


@pytest.fixture
def settings_stub():
    return sys.modules["app.core.config"].settings


@pytest.fixture
def notification_helper():
    return sys.modules["app.helper.notification"].NotificationHelper


@pytest.fixture
def notifier_config():
    return _NotifierConfig
