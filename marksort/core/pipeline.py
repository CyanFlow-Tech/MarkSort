"""管道：source 产出 → 契约校验 → 去重。enricher/sink 的编排在后续步骤接上。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from .container import Container
from .item import Item, ItemError
from .plugin import PluginMeta


@dataclass
class Collected:
    items: List[Item] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    per_source: Dict[str, int] = field(default_factory=dict)
    duplicates: int = 0

    def dump(self, path: str) -> str:
        directory = os.path.dirname(os.path.abspath(path))
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        payload = [item.to_dict() for item in self.items]
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        return path


def pick_sources(container: Container, names: Optional[Sequence[str]] = None) -> List[PluginMeta]:
    sources = container.active("source")
    if not names:
        return sources
    wanted = [n.strip() for n in names if n and n.strip()]
    if any(n.lower() == "all" for n in wanted):
        return sources
    chosen: List[PluginMeta] = []
    for name in wanted:
        hit = next((p for p in sources if p.name == name), None)
        if hit is None:
            raise KeyError("没有启用中的来源插件：%s" % name)
        chosen.append(hit)
    return chosen


async def collect(
    container: Container,
    names: Optional[Sequence[str]] = None,
    limit: Optional[int] = None,
) -> Collected:
    result = Collected()
    seen: Dict[str, str] = {}

    for meta in pick_sources(container, names):
        try:
            settings = container.settings_for(meta)
        except Exception as exc:
            result.warnings.append("%s 配置有问题，跳过：%s" % (meta.name, exc))
            continue
        count = 0
        try:
            async for raw in meta.entry(container, settings):
                item = raw if isinstance(raw, Item) else Item.from_dict(raw)
                try:
                    item.validate()
                except ItemError as exc:
                    result.warnings.append("%s 丢弃一条不合契约的数据：%s" % (meta.name, exc))
                    continue
                if item.key in seen:
                    result.duplicates += 1
                    continue
                seen[item.key] = meta.name
                result.items.append(item)
                count += 1
                if limit is not None and len(result.items) >= limit:
                    result.per_source[meta.name] = count
                    return result
        except Exception as exc:  # 插件内部错误不连坐其它来源
            result.warnings.append("%s 抓取中断：%s: %s" % (meta.name, type(exc).__name__, exc))
        result.per_source[meta.name] = count
    return result
