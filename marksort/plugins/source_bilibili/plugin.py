"""B 站收藏夹来源插件（Python 直连）。

凭据只来自设置，不落代码：settings.local.json 里写 sessdata，
或改成 ${env:BILI_SESSDATA} 从环境变量取。

    [sources.bilibili]
    up_mid   = "398120319"
    sessdata = "${env:BILI_SESSDATA}"
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional

from marksort.core.item import Item, Media
from marksort.core.schema import Schema

name = "bilibili"
kind = "source"
version = "0.1.0"
description = "B 站收藏夹（只读自账号，不下载视频）"
inject = ["log"]

config = {
    "up_mid": Schema.string().required().describe("自己的 B 站 mid"),
    "sessdata": Schema.string().secret().required().describe("Cookie 里的 SESSDATA"),
    "folders": Schema.array(Schema.string()).default([]).describe("只抓这些收藏夹（标题或 id），空表示全部"),
    "page_size": Schema.integer().default(20).minimum(1).maximum(50).describe("每页条数"),
    "order": Schema.enum(("mtime", "view")).default("mtime").describe("排序：收藏时间/播放量"),
    "skip_invalid": Schema.boolean().default(True).describe("跳过已失效条目"),
}

API = "https://api.bilibili.com"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)


class BilibiliError(RuntimeError):
    pass


def _get(path: str, params: Dict[str, Any], sessdata: str, timeout: float = 20.0) -> Dict[str, Any]:
    url = API + path + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "User-Agent": UA,
            "Referer": "https://www.bilibili.com/",
            "Cookie": "SESSDATA=%s" % sessdata,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # 网络/解析错误统一成一句话
        raise BilibiliError("请求 %s 失败：%s" % (path, exc))
    if payload.get("code") != 0:
        raise BilibiliError(
            "%s 返回 code=%s %s" % (path, payload.get("code"), payload.get("message"))
        )
    return payload.get("data") or {}


def list_folders(up_mid: str, sessdata: str) -> List[Dict[str, Any]]:
    data = _get(
        "/x/v3/fav/folder/created/list-all",
        {"up_mid": up_mid, "web_location": "333.1387"},
        sessdata,
    )
    return data.get("list") or []


def iter_folder_medias(
    media_id: Any, sessdata: str, page_size: int, order: str, max_pages: int = 200
) -> Iterator[Dict[str, Any]]:
    page = 1
    while page <= max_pages:
        data = _get(
            "/x/v3/fav/resource/list",
            {
                "media_id": media_id,
                "pn": page,
                "ps": page_size,
                "keyword": "",
                "order": order,
                "type": "0",
                "tid": "0",
                "platform": "web",
                "web_location": "333.1387",
            },
            sessdata,
        )
        medias = data.get("medias") or []
        for media in medias:
            yield media
        if not data.get("has_more") or not medias:
            return
        page += 1


def to_item(media: Dict[str, Any], folder: Dict[str, Any]) -> Optional[Item]:
    bvid = media.get("bvid") or ""
    title = (media.get("title") or "").strip()
    if not bvid or not title or title in ("已失效视频", "失效视频"):
        return None
    upper = media.get("upper") or {}
    counts = media.get("cnt_info") or {}
    cover = (media.get("cover") or "").replace("http://", "https://")
    duration = media.get("duration") or None
    fav_time = media.get("fav_time")
    collected = (
        time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(fav_time)) if fav_time else None
    )
    return Item(
        platform="bilibili",
        external_id=bvid,
        title=title,
        description=(media.get("intro") or "").strip(),
        url="https://www.bilibili.com/video/%s" % bvid,
        cover=cover,
        author={
            "name": upper.get("name") or "",
            "avatar": (upper.get("face") or "").replace("http://", "https://"),
            "id": str(upper.get("mid") or ""),
        },
        tags=[],
        stats={
            "play": str(counts.get("play") or 0),
            "play_text": str(counts.get("view_text_1") or ""),
            "collect": str(counts.get("collect") or 0),
            "danmaku": str(counts.get("danmaku") or 0),
        },
        media=Media(
            kind="iframe",
            url="https://player.bilibili.com/player.html",
            params={
                "aid": media.get("id"),
                "bvid": bvid,
                "p": 1,
                "autoplay": 0,
                "danmaku": 0,
            },
            duration=duration,
        ),
        collected_at=collected,
        raw={
            "folder": {"id": folder.get("id"), "title": folder.get("title")},
            "avid": media.get("id"),
            "fav_time": fav_time,
            "btype": media.get("btype"),
            "attr": media.get("attr"),
        },
    )


async def fetch(ctx, cfg) -> AsyncIterator[Item]:
    log = ctx.service("log")
    up_mid = str(cfg["up_mid"]).strip()
    sessdata = str(cfg["sessdata"]).strip()
    if not up_mid or not sessdata:
        raise BilibiliError("需要 up_mid 与 sessdata；请在设置页或 settings.local.json 里填写")

    folders = list_folders(up_mid, sessdata)
    if not folders:
        raise BilibiliError("这个账号没有可见的收藏夹（Cookie 可能已失效）")
    wanted = [str(x).strip() for x in (cfg["folders"] or [])]
    if wanted:
        selected = [
            f for f in folders if str(f.get("id")) in wanted or f.get("title") in wanted
        ]
    else:
        selected = folders
    if not selected:
        raise BilibiliError("folders 过滤后没有匹配的收藏夹：%s" % ", ".join(wanted))

    log.info("B 站：%d 个收藏夹，开始读取" % len(selected))
    skipped = 0
    for folder in selected:
        count = 0
        for media in iter_folder_medias(
            folder.get("id"), sessdata, int(cfg["page_size"]), str(cfg["order"])
        ):
            item = to_item(media, folder)
            if item is None:
                skipped += 1
                continue
            count += 1
            yield item
        log.info("  %s：%d 条" % (folder.get("title"), count))
    if skipped and cfg["skip_invalid"]:
        log.info("跳过失效条目 %d 条" % skipped)
