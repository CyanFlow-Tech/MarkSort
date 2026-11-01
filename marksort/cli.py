"""命令行入口：python -m marksort <子命令>。

    selftest              跑内核自检
    plugins list|show     看插件清单与契约
    config  check|show    校验 marksort.toml
    fetch  [名字...]      抓取并把 Item 汇总成 JSON
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any, Dict, List, Optional

from .core import config as config_mod
from .core.container import Container, PLUGIN_ROOT
from .core.pipeline import collect
from .core.plugin import PluginError
from .core.schema import SchemaError
from .core.selftest import run as run_selftest


def _build(args: argparse.Namespace) -> Container:
    config = config_mod.load(args.config)
    container = Container(config)
    container.discover_plugins(PLUGIN_ROOT, getattr(args, "plugin_path", None))
    return container


# ---- 子命令 ----


def cmd_selftest(args: argparse.Namespace) -> int:
    total, failures = run_selftest()
    print("")
    if failures:
        print("自检失败 %d/%d：" % (len(failures), total))
        for line in failures:
            print("  - %s" % line)
        return 1
    print("自检通过 %d/%d" % (total, total))
    return 0


def cmd_plugins(args: argparse.Namespace) -> int:
    container = _build(args)
    if args.action == "show":
        if not args.name:
            print("用法：plugins show <插件名>", file=sys.stderr)
            return 2
        meta = container.plugins.get(args.name)
        if meta is None:
            print("没有这个插件：%s" % args.name, file=sys.stderr)
            return 2
        payload: Dict[str, Any] = {
            "name": meta.name,
            "kind": meta.kind,
            "version": meta.version,
            "description": meta.description,
            "entry": meta.entry_name,
            "inject": list(meta.inject),
            "missing_services": container.missing_services(meta),
            "enabled": container.enabled(meta),
            "path": meta.path,
            "config_schema": meta.schema.to_json_schema(),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    plugins = sorted(container.plugins.values(), key=lambda p: (p.kind, p.name))
    if args.json:
        payload = [
            {
                "name": p.name,
                "kind": p.kind,
                "version": p.version,
                "inject": list(p.inject),
                "enabled": container.enabled(p),
                "missing_services": container.missing_services(p),
                "description": p.description,
            }
            for p in plugins
        ]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if not plugins:
        print("没有发现任何插件（目录：%s）" % PLUGIN_ROOT)
        return 0
    print("%-16s %-9s %-8s %-6s %-10s %s" % ("NAME", "KIND", "VERSION", "ON", "INJECT", "DESC"))
    for p in plugins:
        print(
            "%-16s %-9s %-8s %-6s %-10s %s"
            % (
                p.name,
                p.kind,
                p.version,
                "yes" if container.enabled(p) else "no",
                ",".join(p.inject) or "-",
                p.description or "-",
            )
        )
    problems = container.check()
    if problems:
        print("")
        print("依赖问题：")
        for line in problems:
            print("  - %s" % line)
        return 1
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    paths = config_mod.settings_paths()
    path = config_mod.locate(args.config)
    if path is None and not os.path.isfile(paths["default"]):
        print("没有找到 settings.default.json 或 marksort.toml", file=sys.stderr)
        return 2
    container = _build(args)
    if args.action == "show":
        for meta in sorted(container.plugins.values(), key=lambda p: (p.kind, p.name)):
            raw = config_mod.public_view(container.config, meta.kind, meta.name)
            print("[%s.%s] %s" % (config_mod.PLURAL.get(meta.kind, meta.kind), meta.name, json.dumps(raw, ensure_ascii=False)))
        return 0
    failures = container.validate_all_settings()
    shown = path or paths["default"]
    if os.path.isfile(paths["local"]):
        shown += "  +  " + paths["local"]
    print("配置：%s" % shown)
    if not failures:
        print("校验通过：%d 个插件的配置都符合各自的 Schema" % len(container.plugins))
        return 0
    print("校验失败：")
    for name, errors in failures.items():
        print("  [%s]" % name)
        for line in errors:
            print("    - %s" % line)
    return 1


def cmd_fetch(args: argparse.Namespace) -> int:
    container = _build(args)
    if args.no_core_log:
        container.service("log").quiet = True
    result = asyncio.run(collect(container, args.names or None, args.limit))
    if args.json:
        print(json.dumps([item.to_dict() for item in result.items], ensure_ascii=False, indent=2))
    else:
        for item in result.items:
            print(
                "%-8s %-24s %-8s %s"
                % (item.platform, item.external_id[:24], item.media.kind, item.title[:40])
            )
        print("")
        print("共 %d 条" % len(result.items), end="")
        if result.per_source:
            print("（%s）" % "，".join("%s=%d" % kv for kv in sorted(result.per_source.items())), end="")
        if result.duplicates:
            print("，去重 %d 条" % result.duplicates, end="")
        print("")
    for warning in result.warnings:
        print("[warn] %s" % warning, file=sys.stderr)
    if args.out:
        path = result.dump(args.out)
        print("已写出：%s" % path)
    return 0


def _force_utf8_console() -> None:
    """Windows 控制台默认 GBK，中文输出会变乱码。 """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def cmd_ingest(args: argparse.Namespace) -> int:
    from .core.ingest import serve

    serve(port=args.port, data_dir=args.data_dir, verbose=not args.quiet)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .core.server import serve as serve_web

    serve_web(port=args.port, verbose=not args.quiet)
    return 0


# ---- 入口 ----


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="marksort", description="收藏的汇总、分类与门户")
    parser.add_argument("--config", default=None, help="marksort.toml 路径")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("selftest", help="跑内核自检").set_defaults(func=cmd_selftest)

    plugins = sub.add_parser("plugins", help="插件清单")
    plugins.add_argument("action", nargs="?", default="list", choices=["list", "show"])
    plugins.add_argument("name", nargs="?")
    plugins.add_argument("--json", action="store_true")
    plugins.add_argument("--plugin-path", action="append", default=[], help="额外的插件文件或目录")
    plugins.set_defaults(func=cmd_plugins)

    conf = sub.add_parser("config", help="配置校验")
    conf.add_argument("action", nargs="?", default="check", choices=["check", "show"])
    conf.add_argument("--plugin-path", action="append", default=[])
    conf.set_defaults(func=cmd_config)

    fetch = sub.add_parser("fetch", help="抓取并汇总")
    fetch.add_argument("names", nargs="*", help="来源插件名，省略或 all 表示全部")
    fetch.add_argument("--limit", type=int, default=None, help="全局条数上限")
    fetch.add_argument("--out", default=None, help="写出 JSON 文件")
    fetch.add_argument("--json", action="store_true", help="直接打印完整 JSON")
    fetch.add_argument("--plugin-path", action="append", default=[])
    fetch.add_argument("--no-core-log", action="store_true")
    fetch.set_defaults(func=cmd_fetch)

    ingest = sub.add_parser("ingest", help="起本地收数端口，接收浏览器推来的原始数据")
    ingest.add_argument("--port", type=int, default=17330)
    ingest.add_argument("--data-dir", default="data")
    ingest.add_argument("--quiet", action="store_true")
    ingest.set_defaults(func=cmd_ingest)

    web = sub.add_parser("serve", help="起本地设置页与抓取服务")
    web.add_argument("--port", type=int, default=17331)
    web.add_argument("--quiet", action="store_true")
    web.set_defaults(func=cmd_serve)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    _force_utf8_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (PluginError, SchemaError, config_mod.ConfigError) as exc:
        print("错误：%s" % exc, file=sys.stderr)
        return 1
    except KeyError as exc:
        print("错误：%s" % (exc.args[0] if exc.args else exc), file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print("错误：%s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
