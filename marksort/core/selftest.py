"""自检：不依赖 pytest，直接 `python -m marksort selftest`。

覆盖的是「定错了就要全量重抓」的那些地方：Item 契约、Media 的 kind、
配置 Schema 的边角、插件发现与容器装配。
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Callable, List, Tuple

from . import config as config_mod
from .container import Container, PLUGIN_ROOT
from .item import Item, ItemError, Media
from .pipeline import collect
from .schema import Schema, SchemaError

Checks = List[Tuple[str, Callable[[], None]]]


def _expect_error(fn: Callable[[], None], needle: str) -> None:
    try:
        fn()
    except (ItemError, SchemaError, ValueError) as exc:
        assert needle in str(exc), "错误信息里没有 %r：%s" % (needle, exc)
        return
    raise AssertionError("本应报错但没有报错")


def _sample_item() -> Item:
    return Item(
        platform="demo",
        external_id="x-1",
        title="样例",
        url="https://example.com/a",
        cover="/images/a.jpg",
        author={"name": "某人"},
        tags=["a", "b"],
        stats={"liked": 3},
        media=Media(kind="video", url="https://cdn.example.com/a.mp4", duration=12),
    )


def check_item_roundtrip() -> None:
    item = _sample_item().validate()
    again = Item.from_dict(json.loads(json.dumps(item.to_dict(), ensure_ascii=False)))
    assert again.to_dict() == item.to_dict(), "Item 往返不一致"
    assert again.key == "demo:x-1"
    assert again.stats["liked"] == "3", "stats 的值应统一成字符串"


def check_item_rejects_bad_data() -> None:
    _expect_error(lambda: Item(platform="demo", external_id="x", title="").validate(), "title")
    _expect_error(lambda: Item(platform="Demo", external_id="x", title="t").validate(), "platform")
    _expect_error(lambda: Item(platform="demo", external_id="", title="t").validate(), "external_id")
    _expect_error(
        lambda: Item(platform="demo", external_id="x", title="t", url="ftp://a").validate(), "url"
    )
    _expect_error(
        lambda: Item.from_dict({"platform": "demo", "external_id": "x", "title": "t", "bogus": 1}),
        "未知字段",
    )
    _expect_error(
        lambda: Item.from_dict(
            {"schema_version": 99, "platform": "demo", "external_id": "x", "title": "t"}
        ),
        "schema_version",
    )


def check_media_contract() -> None:
    _expect_error(lambda: Media(kind="hologram", url="https://a").validate(), "media.kind")
    _expect_error(lambda: Media(kind="iframe").validate(), "url 或 params")
    assert Media("none").validate().kind == "none"
    assert Media(kind="iframe", params={"cid": 1}).validate().params == {"cid": 1}
    _expect_error(lambda: Media(kind="video", url="https://a", duration=-1).validate(), "负")


def check_schema_defaults_and_errors() -> None:
    shape = {
        "limit": Schema.integer().default(10).minimum(1),
        "tags": Schema.array(Schema.string()).default([]),
        "mode": Schema.enum(("fast", "slow")).default("fast"),
        "token": Schema.string().secret().describe("凭据"),
    }
    schema = Schema.object(shape)
    filled = schema.validate({})
    assert filled == {"limit": 10, "tags": [], "mode": "fast", "token": None}, filled
    _expect_error(lambda: schema.validate({"limit": 0}), "小于")
    _expect_error(lambda: schema.validate({"limit": "10"}), "整数")
    _expect_error(lambda: schema.validate({"nope": 1}), "未知配置项")
    _expect_error(lambda: schema.validate({"tags": ["a", 2]}), "[1]")
    _expect_error(lambda: Schema.object({"k": Schema.string().required()}).validate({}), "必填")
    js = schema.to_json_schema()
    assert js["properties"]["limit"]["default"] == 10
    assert js["properties"]["token"]["x-secret"] is True


def check_env_substitution() -> None:
    os.environ["MARKSORT_SELFTEST_TOKEN"] = "abc"
    value = {"a": "${env:MARKSORT_SELFTEST_TOKEN}", "b": "${env:MARKSORT_MISSING:-fallback}"}
    assert config_mod.substitute_env(value) == {"a": "abc", "b": "fallback"}


def check_plugin_discovery() -> None:
    container = Container({})
    container.discover_plugins(PLUGIN_ROOT)
    names = sorted(container.plugins)
    assert "demo" in names, "没发现演示插件，实际：%s" % names
    demo = container.plugins["demo"]
    assert demo.kind == "source"
    assert container.missing_services(demo) == [], "demo 声明的服务在内核里要存在"
    assert container.check() == []


def check_container_settings() -> None:
    container = Container({})
    container.discover_plugins(PLUGIN_ROOT)
    demo = container.plugins["demo"]
    settings = container.settings_for(demo)
    assert settings["count"] == 3 and settings["with_media"] is True, settings
    active_names = [p.name for p in container.active("source")]
    assert "demo" in active_names, active_names
    disabled = Container({"sources": {"demo": {"enabled": False}}})
    disabled.discover_plugins(PLUGIN_ROOT)
    assert "demo" not in [p.name for p in disabled.active("source")], "enabled=false 应被筛掉"


def check_pipeline() -> None:
    container = Container({})
    container.discover_plugins(PLUGIN_ROOT)
    container.service("log").quiet = True
    result = asyncio.run(collect(container, names=["demo"]))
    assert len(result.items) == 3, "演示插件应产出 3 条，实际 %d" % len(result.items)
    assert result.warnings == [], result.warnings
    assert result.per_source.get("demo") == 3
    kinds = {item.media.kind for item in result.items}
    assert kinds == {"iframe", "video", "none"}, kinds
    limited = asyncio.run(collect(container, names=["demo"], limit=1))
    assert len(limited.items) == 1
    keyed = {item.key for item in result.items}
    assert len(keyed) == len(result.items), "key 必须唯一"


def run() -> Tuple[int, List[str]]:
    checks: Checks = [
        ("Item 往返序列化", check_item_roundtrip),
        ("Item 拒绝坏数据", check_item_rejects_bad_data),
        ("Media 的 kind 契约", check_media_contract),
        ("Schema 默认值与报错", check_schema_defaults_and_errors),
        ("环境变量替换", check_env_substitution),
        ("插件发现", check_plugin_discovery),
        ("容器配置装配", check_container_settings),
        ("管道抓取与去重", check_pipeline),
    ]
    failures: List[str] = []
    for title, fn in checks:
        try:
            fn()
            print("  ok   %s" % title)
        except Exception as exc:
            failures.append("%s: %s: %s" % (title, type(exc).__name__, exc))
            print("  FAIL %s -> %s: %s" % (title, type(exc).__name__, exc))
    return len(checks), failures
