"""marksort.toml 的读取：定位、解析、环境变量替换。

配置按插件种类分节：

    [sources.bilibili]
    enabled = true
    up_mid = "12345"
    sessdata = "${env:BILI_SESSDATA}"

    [enrichers.classifier]
    labels = ["编程", "AI"]
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional

try:  # 3.11+
    import tomllib
except ImportError:  # 3.9 / 3.10
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:  # pragma: no cover
        tomllib = None  # type: ignore[assignment]

PLURAL = {"source": "sources", "enricher": "enrichers", "sink": "sinks"}

DEFAULT_FILENAME = "marksort.toml"

# VSCode 式双层设置：模板入库、真实值在本地
DEFAULT_SETTINGS = "settings.default.json"
LOCAL_SETTINGS = "settings.local.json"

_ENV_RE = re.compile(r"\$\{env:([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def repo_root() -> str:
    """settings.default.json 所在的目录：core/ → marksort/ → 仓库根。"""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def settings_paths() -> Dict[str, str]:
    root = repo_root()
    return {
        "default": os.path.join(root, DEFAULT_SETTINGS),
        "local": os.path.join(root, LOCAL_SETTINGS),
    }


def _read_json(path: str) -> Dict[str, Any]:
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except ValueError as exc:
        raise ConfigError("解析 %s 失败：%s" % (path, exc))
    return data if isinstance(data, dict) else {}


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_settings(explicit_local: Optional[str] = None) -> Dict[str, Any]:
    """模板 → 本地覆盖 → 环境变量替换。"""
    paths = settings_paths()
    merged = _read_json(paths["default"])
    local_path = explicit_local or paths["local"]
    merged = deep_merge(merged, _read_json(local_path))
    return substitute_env(merged)


def save_local(patch: Dict[str, Any], explicit_local: Optional[str] = None) -> str:
    """把改动合并写入 settings.local.json（永不改动模板）。"""
    paths = settings_paths()
    path = explicit_local or paths["local"]
    current = _read_json(path)
    merged = deep_merge(current, patch)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(merged, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return path


class ConfigError(RuntimeError):
    """配置文件本身有问题（找不到 / 语法错 / 结构不对）。"""


def locate(explicit: Optional[str] = None) -> Optional[str]:
    """显式指定 > 当前目录 > 仓库根（marksort/ 的上一级）。"""
    if explicit:
        return explicit if os.path.isfile(explicit) else None
    for candidate in (
        os.path.join(os.getcwd(), DEFAULT_FILENAME),
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", DEFAULT_FILENAME),
    ):
        path = os.path.abspath(candidate)
        if os.path.isfile(path):
            return path
    return None


def load(path: Optional[str] = None) -> Dict[str, Any]:
    """优先读 JSON 双层设置；没有就回退 marksort.toml。"""
    if os.path.isfile(settings_paths()["default"]) or os.path.isfile(settings_paths()["local"]):
        return load_settings(path)
    if tomllib is None:  # pragma: no cover
        raise ConfigError("缺少 TOML 解析器：请用 Python 3.11+ 或 pip install tomli")
    resolved = locate(path)
    if resolved is None:
        return {}
    try:
        with open(resolved, "rb") as handle:
            data = tomllib.load(handle)
    except Exception as exc:  # tomllib.TOMLDecodeError 在 3.9 不存在
        raise ConfigError("解析 %s 失败：%s" % (resolved, exc))
    if not isinstance(data, dict):
        raise ConfigError("%s 的顶层必须是表" % resolved)
    return substitute_env(data)


def substitute_env(value: Any) -> Any:
    """把 ${env:NAME} / ${env:NAME:-fallback} 换成环境变量值。"""

    if isinstance(value, str):
        def repl(match: "re.Match[str]") -> str:
            name, fallback = match.group(1), match.group(2)
            default = "" if fallback is None else fallback
            return os.environ.get(name, default)

        return _ENV_RE.sub(repl, value)
    if isinstance(value, list):
        return [substitute_env(v) for v in value]
    if isinstance(value, dict):
        return {k: substitute_env(v) for k, v in value.items()}
    return value


def section(config: Dict[str, Any], kind: str, name: str) -> Dict[str, Any]:
    """取某插件自己的配置表，缺省为空表。"""
    plural = PLURAL.get(kind, kind)
    table = config.get(plural) or {}
    if not isinstance(table, dict):
        raise ConfigError("[%s] 必须是表" % plural)
    own = table.get(name) or {}
    if not isinstance(own, dict):
        raise ConfigError("[%s.%s] 必须是表" % (plural, name))
    return own


def is_enabled(config: Dict[str, Any], kind: str, name: str) -> bool:
    """未写 enabled 视为启用；写了就按写的。"""
    own = section(config, kind, name)
    flag = own.get("enabled", True)
    return bool(flag)


def public_view(config: Dict[str, Any], kind: str, name: str) -> Dict[str, Any]:
    """给日志/报表用的配置视图：把疑似凭据的字段打码。"""
    own = dict(section(config, kind, name))
    for key in list(own):
        lowered = key.lower()
        if any(token in lowered for token in ("cookie", "sessdata", "token", "secret", "password")):
            own[key] = "***" if own[key] else ""
    return own
