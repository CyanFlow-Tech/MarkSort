"""插件的加载与契约检查。

插件就是一个 Python 模块，模块级声明这几样东西：

    name        = "bilibili"          # 必填，唯一
    kind        = "source"            # 必填，source/enricher/sink
    version     = "0.1.0"             # 选填
    description = "B 站收藏夹"         # 选填
    inject      = ["http"]            # 选填，需要的内核服务
    config      = {"up_mid": Schema.string().required()}
    async def fetch(ctx, cfg): ...    # source 的入口

内核不认识类：插件是模块，入口是函数，够用且好写。
"""

from __future__ import annotations

import importlib
import inspect
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .schema import Schema

KINDS: Tuple[str, ...] = ("source", "enricher", "sink")

ENTRY = {"source": "fetch", "enricher": "enrich", "sink": "write"}


class PluginError(RuntimeError):
    """插件不满足契约。"""


@dataclass
class PluginMeta:
    name: str
    kind: str
    module: Any
    path: str
    version: str = "0.0.0"
    description: str = ""
    inject: Tuple[str, ...] = ()
    config: Dict[str, Schema] = field(default_factory=dict)

    @property
    def entry_name(self) -> str:
        return ENTRY[self.kind]

    @property
    def entry(self) -> Any:
        return getattr(self.module, self.entry_name)

    @property
    def schema(self) -> Schema:
        return Schema.object(self.config)

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return "<PluginMeta %s %s>" % (self.kind, self.name)


def load(module: Any, path: str) -> PluginMeta:
    """把一个已导入的模块变成 PluginMeta，顺带查契约。"""
    name = getattr(module, "name", None)
    if not name or not isinstance(name, str):
        raise PluginError("%s 缺少模块级 name" % path)
    kind = getattr(module, "kind", None)
    if kind not in KINDS:
        raise PluginError("%s 的 kind 必须是 %s，收到 %r" % (path, "/".join(KINDS), kind))
    entry_name = ENTRY[kind]
    entry = getattr(module, entry_name, None)
    if entry is None:
        raise PluginError("%s（kind=%s）缺少入口函数 %s" % (path, kind, entry_name))
    if not callable(entry):
        raise PluginError("%s 的 %s 不是可调用对象" % (path, entry_name))
    if not (inspect.iscoroutinefunction(entry) or inspect.isasyncgenfunction(entry)):
        raise PluginError("%s 的 %s 必须是 async 函数或 async 生成器" % (path, entry_name))
    inject = getattr(module, "inject", ())
    if isinstance(inject, str):
        inject = (inject,)
    if not isinstance(inject, (list, tuple)):
        raise PluginError("%s 的 inject 必须是字符串数组" % path)
    config = getattr(module, "config", {}) or {}
    if not isinstance(config, dict) or any(not isinstance(v, Schema) for v in config.values()):
        raise PluginError("%s 的 config 必须是 {字段名: Schema} 的表" % path)
    return PluginMeta(
        name=name.strip(),
        kind=kind,
        module=module,
        path=path,
        version=str(getattr(module, "version", "0.0.0")),
        description=str(getattr(module, "description", "")),
        inject=tuple(str(x) for x in inject),
        config=dict(config),
    )


def load_file(py_path: str, module_name: Optional[str] = None) -> PluginMeta:
    """按文件路径导入插件模块（支持仓库外的第三方插件目录）。"""
    py_path = os.path.abspath(py_path)
    if not os.path.isfile(py_path):
        raise PluginError("插件文件不存在：%s" % py_path)
    stem = os.path.splitext(os.path.basename(os.path.dirname(py_path)))[0] or "plugin"
    mod_name = module_name or ("marksort_plugin_%s" % stem)
    spec = importlib.util.spec_from_file_location(mod_name, py_path)
    if spec is None or spec.loader is None:
        raise PluginError("无法为 %s 建立导入规格" % py_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return load(module, py_path)


def discover(plugin_root: str, extra_paths: Optional[List[str]] = None) -> List[PluginMeta]:
    """扫描插件目录：<plugin_root>/<pkg>/plugin.py。

    内置插件用包导入（模块名稳定、可互相引用），仓库外目录用文件导入。
    """
    found: List[PluginMeta] = []
    if os.path.isdir(plugin_root):
        for entry in sorted(os.listdir(plugin_root)):
            pkg_dir = os.path.join(plugin_root, entry)
            py_path = os.path.join(pkg_dir, "plugin.py")
            if not os.path.isdir(pkg_dir) or not os.path.isfile(py_path):
                continue
            mod_name = "%s.%s.plugin" % (_package_of(plugin_root), entry)
            module = importlib.import_module(mod_name)
            found.append(load(module, py_path))
    for extra in extra_paths or ():
        extra = os.path.abspath(extra)
        candidates: List[str] = []
        if os.path.isdir(extra):
            inner = os.path.join(extra, "plugin.py")
            if os.path.isfile(inner):
                candidates.append(inner)
            else:
                for entry in sorted(os.listdir(extra)):
                    py_path = os.path.join(extra, entry, "plugin.py")
                    if os.path.isfile(py_path):
                        candidates.append(py_path)
        elif extra.endswith(".py"):
            candidates.append(extra)
        for py_path in candidates:
            found.append(load_file(py_path))
    serialized: Dict[str, str] = {}
    for meta in found:
        if meta.name in serialized:
            raise PluginError(
                "插件名重复：%s（%s 与 %s）" % (meta.name, serialized[meta.name], meta.path)
            )
        serialized[meta.name] = meta.path
    return found


def _package_of(plugin_root: str) -> str:
    """由目录路径推出包名，例如 .../marksort/plugins -> marksort.plugins。"""
    parts = []
    current = os.path.abspath(plugin_root)
    while current and os.path.isfile(os.path.join(current, "__init__.py")):
        parts.append(os.path.basename(current))
        current = os.path.dirname(current)
    if not parts:
        raise PluginError("插件目录不是可导入的包：%s" % plugin_root)
    return ".".join(reversed(parts))
