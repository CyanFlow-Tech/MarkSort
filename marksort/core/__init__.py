"""内核：数据契约、配置 Schema、插件容器、抓取管道。"""

from .container import Container
from .item import MEDIA_KINDS, SCHEMA_VERSION, Item, ItemError, Media
from .plugin import KINDS, PluginError, PluginMeta
from .schema import Schema, SchemaError

__all__ = [
    "Container",
    "Item",
    "ItemError",
    "Media",
    "MEDIA_KINDS",
    "SCHEMA_VERSION",
    "Schema",
    "SchemaError",
    "PluginMeta",
    "PluginError",
    "KINDS",
]
