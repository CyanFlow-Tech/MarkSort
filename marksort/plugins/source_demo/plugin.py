"""演示来源插件：不联网，产出固定几条数据，用来验证容器与管道是否通。

它的存在意义是把「插件契约是否可用」和「网络、Cookie、签名是否可用」解耦：
前者挂了那是内核的事，后者挂了那是账号的事。
"""

from __future__ import annotations

from typing import AsyncIterator

from marksort.core.item import Item, Media
from marksort.core.schema import Schema

name = "demo"
kind = "source"
version = "0.1.0"
description = "演示来源：产出 3 条本地假数据，不联网"
inject = ["clock"]

config = {
    "count": Schema.integer().default(3).describe("产出条数").minimum(1).maximum(20),
    "with_media": Schema.boolean().default(True).describe("是否带播放信息"),
}

_SAMPLES = [
    {
        "external_id": "demo-iframe",
        "title": "一条用 iframe 播放的收藏",
        "description": "这类内容前端用播放器组件嵌进去，跟平台叫什么无关。",
        "tags": ["演示", "视频"],
        "media": Media(
            kind="iframe",
            url="https://player.example.com/player.html",
            params={"aid": 1, "bvid": "BV1demo", "cid": 2, "p": 1},
            duration=612,
        ),
        "stats": {"play": "1204", "collect": "37"},
    },
    {
        "external_id": "demo-video",
        "title": "一条直接给视频地址的收藏",
        "description": "同一个 media 字段，kind 换掉，前端渲染器就换掉。",
        "tags": ["演示", "视频"],
        "media": Media(kind="video", url="https://cdn.example.com/clip.mp4", duration=95),
        "stats": {"liked": "58"},
    },
    {
        "external_id": "demo-image",
        "title": "一条图文收藏",
        "description": "只有封面，media 为 none，卡片照样渲染。",
        "tags": ["演示", "图文"],
        "media": Media("none"),
        "stats": {},
    },
]


async def fetch(ctx, cfg) -> AsyncIterator[Item]:
    clock = ctx.service("clock")
    stamp = clock.now()
    count = int(cfg["count"])
    for index in range(count):
        sample = _SAMPLES[index % len(_SAMPLES)]
        media = sample["media"] if cfg["with_media"] else Media("none")
        yield Item(
            platform="demo",
            external_id="%s-%d" % (sample["external_id"], index),
            title=sample["title"],
            description=sample["description"],
            url="https://example.com/items/%d" % index,
            cover="/images_demo/cover-%d.jpg" % (index % len(_SAMPLES)),
            author={"name": "演示作者", "avatar": "/images_demo/avatar.jpg", "id": "demo-user"},
            tags=list(sample["tags"]),
            stats=dict(sample["stats"]),
            media=media,
            collected_at=stamp,
            raw={"generated_by": "source_demo"},
        )
