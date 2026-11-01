"""容器：内核服务的注册表 + 插件注册表。

对应 dsh 里 ctx.service / inject 的那一层，但只有两个概念：

* 服务（service）：内核提供的能力，插件用 inject 声明自己需要哪个
* 插件（plugin）：按 kind 分表，容器负责发现、校验依赖、按配置筛选

不提供插件间通信、不做热插拔、不做沙箱——这是刻意的取舍。
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Iterable, List, Optional

from . import config as config_mod
from .plugin import KINDS, PluginMeta, discover
from .schema import SchemaError

PLUGIN_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugins")


class Container:
    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self.config: Dict[str, Any] = config or {}
        self.services: Dict[str, Any] = {}
        self.plugins: Dict[str, PluginMeta] = {}
        self._provide_core_services()

    # ---- 服务 ----

    def _provide_core_services(self) -> None:
        self.services["log"] = _Logger()
        self.services["clock"] = _Clock()

    def provide(self, name: str, service: Any) -> None:
        self.services[name] = service

    def service(self, name: str) -> Any:
        if name not in self.services:
            raise KeyError("内核没有提供这个服务：%s（已有：%s）" % (name, ", ".join(sorted(self.services))))
        return self.services[name]

    # ---- 插件 ----

    def discover_plugins(self, plugin_root: str = PLUGIN_ROOT, extra_paths: Optional[List[str]] = None) -> None:
        for meta in discover(plugin_root, extra_paths):
            self.register(meta)

    def register(self, meta: PluginMeta) -> None:
        if meta.name in self.plugins:
            raise ValueError("插件名重复：%s" % meta.name)
        self.plugins[meta.name] = meta

    def of_kind(self, kind: str) -> List[PluginMeta]:
        return sorted((p for p in self.plugins.values() if p.kind == kind), key=lambda p: p.name)

    def missing_services(self, meta: PluginMeta) -> List[str]:
        return [name for name in meta.inject if name not in self.services]

    def check(self) -> List[str]:
        """返回所有不放心的点；空数组表示全部就绪。"""
        problems: List[str] = []
        for meta in self.plugins.values():
            missing = self.missing_services(meta)
            if missing:
                problems.append("%s 缺少服务：%s" % (meta.name, ", ".join(missing)))
        return problems

    # ---- 配置 ----

    def settings_for(self, meta: PluginMeta) -> Dict[str, Any]:
        """取配置 → 校验 → 填默认值。缺项/多余项都会报错，方便发现拼写错误。"""
        raw = config_mod.section(self.config, meta.kind, meta.name)
        raw = {k: v for k, v in raw.items() if k != "enabled"}
        return meta.schema.validate(raw)

    def enabled(self, meta: PluginMeta) -> bool:
        return config_mod.is_enabled(self.config, meta.kind, meta.name)

    def active(self, kind: Optional[str] = None) -> List[PluginMeta]:
        """按配置筛出的启用插件；kind 为空则包含全部种类。"""
        kinds: Iterable[str] = (kind,) if kind else KINDS
        selected: List[PluginMeta] = []
        for one_kind in kinds:
            selected.extend(p for p in self.of_kind(one_kind) if self.enabled(p))
        return selected

    def validate_all_settings(self) -> Dict[str, List[str]]:
        """逐插件校验配置，返回 {插件名: [错误...]}，空表表示全通过。"""
        failures: Dict[str, List[str]] = {}
        for meta in self.plugins.values():
            try:
                self.settings_for(meta)
            except SchemaError as exc:
                failures[meta.name] = exc.flat
        return failures


class _Logger:
    def __init__(self) -> None:
        self.quiet = False

    def info(self, message: str) -> None:
        if not self.quiet:
            print("[info] %s" % message)

    def warn(self, message: str) -> None:
        if not self.quiet:
            print("[warn] %s" % message)

    def error(self, message: str) -> None:
        print("[error] %s" % message)


class _Clock:
    def now(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())
