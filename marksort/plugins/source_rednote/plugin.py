"""小红书收藏来源插件。

签名用 xhshow（复刻网页端 x-s/x-t），HTTP 用 rnet（TLS 指纹贴近真实浏览器）。
凭据只来自设置：a1 / web_session / web_id 三项 Cookie，从浏览器里复制。

    [sources.rednote]
    user_id     = "5d2287cd0000000016000fd7"
    a1          = "${env:REDNOTE_A1}"
    web_session = "${env:REDNOTE_WEB_SESSION}"
    web_id      = "${env:REDNOTE_WEB_ID}"

小红书没有公开的嵌入播放器，所以条目统一 media.kind = "none"，
卡片显示封面，点击走原文链接。
"""

from __future__ import annotations

import asyncio
import random
from typing import Any, AsyncIterator, Dict, List, Optional

from marksort.core.item import Item, Media
from marksort.core.schema import Schema

name = "rednote"
kind = "source"
version = "0.1.0"
description = "小红书收藏（需要 a1 / web_session / web_id）"
inject = ["log"]

config = {
    "user_id": Schema.string().required().describe("自己的小红书 user_id"),
    "a1": Schema.string().secret().required().describe("Cookie 里的 a1"),
    "web_session": Schema.string().secret().required().describe("Cookie 里的 web_session"),
    "web_id": Schema.string().secret().describe("Cookie 里的 webId（可留空）"),
    "max_pages": Schema.integer().default(200).minimum(1).maximum(400).describe("最多翻多少页（每页 10 条）"),
    "page_delay": Schema.number().default(2.0).minimum(0.5).maximum(10.0).describe("页间隔秒数，太快会被风控"),
}

HOST = "https://edith.xiaohongshu.com"
COLLECT_URI = "/api/sns/web/v2/note/collect/page"
APP_ID = "xhs-pc-web"


class RednoteError(RuntimeError):
    pass


def _imports():
    try:
        from xhshow import Xhshow  # type: ignore
        from rnet import Client, Impersonate  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RednoteError(
            "缺少依赖 %s；用 uv sync 安装（xhshow 需要 Python >= 3.10）" % exc
        )
    return Xhshow, Client


async def _collect_page(
    client: Any,
    signer: Any,
    cookies: Dict[str, str],
    user_id: str,
    cursor: str,
) -> Dict[str, Any]:
    # 接口每页固定回 10 条，num 传什么都不会变多
    params = {
        "num": 10,
        "cursor": cursor,
        "user_id": user_id,
        "image_formats": "jpg,webp,avif",
        "xsec_token": "",
        "xsec_source": "",
    }
    # 签名基于参数顺序与原始类型：url 必须用 signer.build_url 生成，
    # 自己 urlencode 会让 x-s 与真实请求串对不上（服务端直接 code=-1）
    headers = signer.sign_headers_get(
        uri=COLLECT_URI,
        cookies=cookies,
        params=params,
        xsec_appid=APP_ID,
        user_id=user_id,
    )
    url = signer.build_url(HOST + COLLECT_URI, params)
    response = await client.get(url, cookies=cookies, headers=headers)
    payload = await response.json()
    if not payload.get("success"):
        raise RednoteError(
            "收藏接口返回 code=%s %s" % (payload.get("code"), payload.get("msg"))
        )
    return payload.get("data") or {}


async def _collect_with_backoff(
    client: Any,
    signer: Any,
    cookies: Dict[str, str],
    user_id: str,
    cursor: str,
    log: Any,
    retries: int = 3,
) -> Optional[Dict[str, Any]]:
    """被风控（code=-3）时指数退避重试；彻底失败返回 None。"""
    wait = 10.0
    for attempt in range(retries + 1):
        try:
            return await _collect_page(client, signer, cookies, user_id, cursor)
        except RednoteError as exc:
            if "code=-3" in str(exc) and attempt < retries:
                log.warn("小红书触发风控，%d 秒后重试（第 %d 次）" % (wait, attempt + 1))
                await asyncio.sleep(wait)
                wait *= 2
                continue
            raise
    return None


def _first_image(cover: Any) -> str:
    if isinstance(cover, dict):
        for key in ("url_default", "url_pre", "url"):
            if cover.get(key):
                return str(cover[key])
        info = cover.get("info_list") or []
        if info and isinstance(info[0], dict) and info[0].get("url"):
            return str(info[0]["url"])
    return ""


def to_item(note: Dict[str, Any], user_id: str) -> Optional[Item]:
    note_id = note.get("note_id") or note.get("id")
    title = (note.get("display_title") or "").strip()
    if not note_id:
        return None
    if not title:
        title = (note.get("note_card") or {}).get("display_title") or "（无标题）"
    cover = _first_image(note.get("cover"))
    user = note.get("user") or {}
    interact = note.get("interact_info") or {}
    token = note.get("xsec_token") or ""
    url = "https://www.xiaohongshu.com/explore/%s" % note_id
    if token:
        url += "?xsec_token=%s&xsec_source=pc_collect" % token
    return Item(
        platform="rednote",
        external_id=str(note_id),
        title=title,
        description="",
        url=url,
        cover=cover,
        author={
            "name": user.get("nickname") or "",
            "avatar": user.get("avatar") or "",
            "id": str(user.get("user_id") or ""),
        },
        tags=[],
        stats={
            "liked": str(interact.get("liked_count") or ""),
            "collected": str(interact.get("collected_count") or ""),
        },
        # 小红书没有官方嵌入播放器：不做站内播放，点击走原文
        media=Media(kind="none"),
        collected_at=None,
        raw={"note_type": note.get("type"), "owner": user_id, "xsec_token": token},
    )


async def fetch(ctx, cfg) -> AsyncIterator[Item]:
    log = ctx.service("log")
    Xhshow, Client = _imports()
    from rnet import Impersonate  # type: ignore

    user_id = str(cfg["user_id"]).strip()
    cookies = {"a1": str(cfg["a1"]).strip(), "web_session": str(cfg["web_session"]).strip()}
    if cfg["web_id"]:
        cookies["webId"] = str(cfg["web_id"]).strip()
    if not user_id or not cookies["a1"] or not cookies["web_session"]:
        raise RednoteError("需要 user_id / a1 / web_session，请在设置页填写")

    signer = Xhshow()
    client = Client(impersonate=Impersonate.Chrome137, verify=False)
    cursor = ""
    page = 0
    total = 0
    max_pages = int(cfg["max_pages"])
    delay = float(cfg["page_delay"])

    while page < max_pages:
        data = await _collect_with_backoff(client, signer, cookies, user_id, cursor, log)
        if data is None:
            break
        notes: List[Dict[str, Any]] = data.get("notes") or []
        if not notes:
            break
        for note in notes:
            item = to_item(note, user_id)
            if item is None:
                continue
            total += 1
            yield item
        page += 1
        log.info("小红书：第 %d 页，累计 %d 条" % (page, total))
        if not data.get("has_more"):
            break
        cursor = data.get("cursor") or ""
        if not cursor:
            break
        await asyncio.sleep(delay * (1.0 + 0.25 * random.random()))
