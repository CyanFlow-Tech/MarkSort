"""数据契约。

插件只被允许用 Item 与外界交换数据：source 产出 Item，enricher 改写加工字段，
sink 消费 Item，前端也只看 Item。平台差异必须落到字段（尤其是 media.kind），
不许落到「平台名 + if 分支」——这是整个插件化成立的前提。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = 1

# media.kind 决定前端用哪个渲染器；新增平台优先复用已有 kind。
MEDIA_KINDS = ("iframe", "video", "image", "none")

_PLATFORM_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


class ItemError(ValueError):
    """Item 违反数据契约。"""


def _text(value: Any, name: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ItemError("%s 必须是字符串，收到 %s" % (name, type(value).__name__))
    text = value.strip()
    if not text and not allow_empty:
        raise ItemError("%s 不能为空" % name)
    return text


@dataclass
class Media:
    """一条收藏的播放/查看方式。前端按 kind 选渲染器，不认识平台。"""

    kind: str = "none"
    url: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    duration: Optional[int] = None

    def validate(self) -> "Media":
        if self.kind not in MEDIA_KINDS:
            raise ItemError(
                "media.kind 必须是 %s 之一，收到 %r" % ("/".join(MEDIA_KINDS), self.kind)
            )
        if self.kind != "none" and not self.url and not self.params:
            raise ItemError("media.kind=%s 时 url 或 params 至少要给一个" % self.kind)
        if self.duration is not None:
            if isinstance(self.duration, bool) or not isinstance(self.duration, int):
                raise ItemError("media.duration 必须是整数秒")
            if self.duration < 0:
                raise ItemError("media.duration 不能为负")
        if self.params and not isinstance(self.params, dict):
            raise ItemError("media.params 必须是对象")
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "url": self.url,
            "params": dict(self.params),
            "duration": self.duration,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "Media":
        if data is None:
            return cls("none")
        if not isinstance(data, dict):
            raise ItemError("media 必须是对象或 null")
        media = cls(
            kind=data.get("kind") or "none",
            url=data.get("url") or "",
            params=dict(data.get("params") or {}),
            duration=data.get("duration"),
        )
        return media.validate()


@dataclass
class Item:
    """一条收藏。跨平台唯一形状，任何插件看到的人都长这样。"""

    platform: str
    external_id: str
    title: str
    description: str = ""
    url: str = ""
    cover: str = ""
    author: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    category: Optional[str] = None
    summary: Optional[str] = None
    stats: Dict[str, str] = field(default_factory=dict)
    media: Optional[Media] = None
    collected_at: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    # ---- 校验 ----

    def validate(self) -> "Item":
        if not isinstance(self.platform, str) or not _PLATFORM_RE.match(self.platform):
            raise ItemError(
                "platform 必须是 2-32 位小写字母/数字/下划线且以字母开头，收到 %r"
                % (self.platform,)
            )
        self.external_id = _text(self.external_id, "external_id")
        self.title = _text(self.title, "title")
        self.description = _text(self.description, "description", allow_empty=True)
        if self.url:
            self.url = _text(self.url, "url")
            if not _URL_RE.match(self.url):
                raise ItemError("url 必须以 http:// 或 https:// 开头：%r" % self.url)
        if self.cover:
            self.cover = _text(self.cover, "cover")
            if not _URL_RE.match(self.cover) and not self.cover.startswith(("/", "\\")):
                raise ItemError("cover 必须是 http(s) 地址或 / 开头的本地路径：%r" % self.cover)
        if not isinstance(self.tags, list):
            raise ItemError("tags 必须是数组")
        self.tags = [_text(t, "tags[%d]" % i) for i, t in enumerate(self.tags)]
        if self.author:
            if not isinstance(self.author, dict):
                raise ItemError("author 必须是对象")
            if "name" in self.author:
                self.author = dict(self.author)
                self.author["name"] = _text(self.author["name"], "author.name", allow_empty=True)
        if self.stats:
            if not isinstance(self.stats, dict):
                raise ItemError("stats 必须是对象")
            self.stats = {str(k): str(v) for k, v in self.stats.items() if v is not None}
        if not isinstance(self.raw, dict):
            raise ItemError("raw 必须是对象")
        for name in ("category", "summary", "collected_at"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise ItemError("%s 必须是字符串或 null" % name)
        if self.media is None:
            self.media = Media("none")
        elif not isinstance(self.media, Media):
            self.media = Media.from_dict(self.media)
        self.media.validate()
        return self

    # ---- 序列化 ----

    @property
    def key(self) -> str:
        """跨源去重键。"""
        return "%s:%s" % (self.platform, self.external_id)

    def to_dict(self) -> Dict[str, Any]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "platform": self.platform,
            "external_id": self.external_id,
            "title": self.title,
            "description": self.description,
            "url": self.url,
            "cover": self.cover,
            "author": dict(self.author),
            "tags": list(self.tags),
            "category": self.category,
            "summary": self.summary,
            "stats": dict(self.stats),
            "media": (self.media or Media("none")).to_dict(),
            "collected_at": self.collected_at,
            "raw": dict(self.raw),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Item":
        if not isinstance(data, dict):
            raise ItemError("Item 必须是对象")
        known = {
            "platform", "external_id", "title", "description", "url", "cover",
            "author", "tags", "category", "summary", "stats", "media",
            "collected_at", "raw", "schema_version",
        }
        unknown = set(data) - known
        if unknown:
            raise ItemError("未知字段：%s" % ", ".join(sorted(unknown)))
        version = data.get("schema_version", SCHEMA_VERSION)
        if version != SCHEMA_VERSION:
            raise ItemError(
                "schema_version 不兼容：文件是 %r，内核是 %r" % (version, SCHEMA_VERSION)
            )
        item = cls(
            platform=data.get("platform", ""),
            external_id=data.get("external_id", ""),
            title=data.get("title", ""),
            description=data.get("description") or "",
            url=data.get("url") or "",
            cover=data.get("cover") or "",
            author=dict(data.get("author") or {}),
            tags=list(data.get("tags") or []),
            category=data.get("category"),
            summary=data.get("summary"),
            stats=dict(data.get("stats") or {}),
            media=Media.from_dict(data["media"]) if data.get("media") else None,
            collected_at=data.get("collected_at"),
            raw=dict(data.get("raw") or {}),
            schema_version=version,
        )
        return item.validate()
