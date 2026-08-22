# -*- coding: utf-8 -*-
"""为 plugins.v2/hhclublottery 提供 MoviePilot 主程序的最小桩实现，
使插件可以脱离 MoviePilot 运行环境被单独导入和测试。

**桩件装完就地把插件模块加载掉，然后把 sys.modules 恢复原样。**
每个插件的 conftest 都往 `app.*` 这几个全局名字上装自己的桩，谁后装谁覆盖；
插件模块一旦加载完就持有了 settings / logger / _PluginBase 的直接引用，
之后 sys.modules 怎么变都与它无关。不恢复的话，另一个插件的 session 级
fixture 晚一步加载，就会绑到这里的桩上（它的 NotificationType 没有
SiteMessage、_PluginBase 没有 update_config），整批测试跟着一起挂。

这里写成普通模块而不是直接写在 conftest 里：`--import-mode=importlib` 下
conftest 由 pytest 单独加载，测试文件再 import 一次会拿到第二个副本，
插件模块就成了两个不同的对象，monkeypatch 打在哪个上都不算数。
"""
import enum
import importlib.util
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_DIR = REPO_ROOT / "plugins.v2" / "hhclublottery"

# 抽奖核心在插件目录下，插件模块 import 它时要找得到
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))


# ---------------- MoviePilot 主程序桩 ----------------

class _Settings:
    TZ = "Asia/Shanghai"
    PROXY = {"http": "http://127.0.0.1:7890"}
    VERSION_FLAG = "v2"
    # 数据页上的按钮要带着它去调插件 API
    API_TOKEN = "stub-api-token"


class _NotificationType(enum.Enum):
    SiteMessage = "站点消息"
    Plugin = "插件通知"


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


class _Logger:
    @staticmethod
    def info(*_a, **_k):
        pass

    @staticmethod
    def warning(*_a, **_k):
        pass

    @staticmethod
    def warn(*_a, **_k):
        pass

    @staticmethod
    def error(*_a, **_k):
        pass

    @staticmethod
    def debug(*_a, **_k):
        pass


class _PluginBase:
    """最小插件基类：配置和数据读写走内存字典，post_message 记录调用。"""

    def __init__(self):
        self._store = {}
        self._config = {}
        self.messages = []

    def update_config(self, config, plugin_id=None):
        self._config.update(config)
        return True

    def get_config(self, plugin_id=None):
        return self._config

    def save_data(self, key, value, plugin_id=None):
        self._store[key] = value

    def get_data(self, key=None, plugin_id=None):
        return self._store.get(key) if key else self._store

    def del_data(self, key, plugin_id=None):
        return self._store.pop(key, None)

    def post_message(self, **kwargs):
        self.messages.append(kwargs)


_STUB_NAMES = ("app", "app.core", "app.core.config", "app.core.event", "app.log",
               "app.plugins", "app.schemas", "app.schemas.types", "app.helper", "app.db")


def _load_plugin_module():
    """装桩 → 加载插件 → 还原 sys.modules。"""
    saved = {name: sys.modules.get(name) for name in _STUB_NAMES}

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
    module("app.log", logger=_Logger())
    module("app.plugins", _PluginBase=_PluginBase)
    module("app.schemas", NotificationType=_NotificationType)
    module("app.schemas.types", EventType=_EventType)
    module("app.helper")
    module("app.db")

    try:
        spec = importlib.util.spec_from_file_location(
            "hh_plugin", PLUGIN_DIR / "__init__.py",
            submodule_search_locations=[str(PLUGIN_DIR)])
        mod = importlib.util.module_from_spec(spec)
        sys.modules["hh_plugin"] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        for name, original in saved.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


HH = _load_plugin_module()
