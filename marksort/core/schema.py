"""配置 Schema：插件用声明式方式描述自己的配置，内核负责校验与填默认值。

刻意只做子集——string/integer/number/boolean/array/object/enum，
够描述抓取参数与分类器设置即可。不引入 pydantic 等依赖。
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple

_MISSING = object()


class SchemaError(ValueError):
    """配置校验失败。errors 是 {字段路径: 说明}。"""

    def __init__(self, errors: Dict[str, str]) -> None:
        self.errors = dict(errors)
        super().__init__("; ".join("%s: %s" % kv for kv in sorted(self.errors.items())))

    @property
    def flat(self) -> List[str]:
        return ["%s: %s" % kv for kv in sorted(self.errors.items())]


class Schema:
    """单个配置项的规则。链式方法就地修改并返回自身。"""

    def __init__(
        self,
        kind: str,
        *,
        item: "Optional[Schema]" = None,
        shape: "Optional[Dict[str, Schema]]" = None,
        choices: Tuple[Any, ...] = (),
        default: Any = _MISSING,
        required: bool = False,
        secret: bool = False,
        description: str = "",
        minimum: Any = None,
        maximum: Any = None,
    ) -> None:
        self.kind = kind
        self.item = item
        self.shape = shape
        self.choices = tuple(choices)
        self._default = default
        self._required = required
        self._secret = secret
        self._description = description
        # 属性名统一加下划线，避免和链式方法同名（.minimum() / .maximum()）
        self._minimum = minimum
        self._maximum = maximum

    # ---- 链式修饰 ----

    def required(self) -> "Schema":
        self._required = True
        return self

    def default(self, value: Any) -> "Schema":
        self._default = value
        return self

    def secret(self) -> "Schema":
        self._secret = True
        return self

    def describe(self, text: str) -> "Schema":
        self._description = text
        return self

    def minimum(self, value: Any) -> "Schema":
        self._minimum = value
        return self

    def maximum(self, value: Any) -> "Schema":
        self._maximum = value
        return self

    @property
    def is_required(self) -> bool:
        return self._required

    @property
    def is_secret(self) -> bool:
        return self._secret

    @property
    def description(self) -> str:
        return self._description

    @property
    def has_default(self) -> bool:
        return self._default is not _MISSING

    @property
    def default_value(self) -> Any:
        return copy.deepcopy(self._default)

    # ---- 工厂 ----

    @classmethod
    def string(cls, **kw: Any) -> "Schema":
        return cls("string", **kw)

    @classmethod
    def integer(cls, **kw: Any) -> "Schema":
        return cls("integer", **kw)

    @classmethod
    def number(cls, **kw: Any) -> "Schema":
        return cls("number", **kw)

    @classmethod
    def boolean(cls, **kw: Any) -> "Schema":
        return cls("boolean", **kw)

    @classmethod
    def array(cls, item: "Schema", **kw: Any) -> "Schema":
        return cls("array", item=item, **kw)

    @classmethod
    def object(cls, shape: "Dict[str, Schema]", **kw: Any) -> "Schema":
        return cls("object", shape=dict(shape), **kw)

    @classmethod
    def enum(cls, choices: Tuple[Any, ...], **kw: Any) -> "Schema":
        return cls("enum", choices=tuple(choices), **kw)

    # ---- 校验 ----

    def validate(self, value: Any = _MISSING) -> Any:
        if value is _MISSING or value is None:
            if self.has_default:
                return self.default_value
            if self._required:
                raise SchemaError({"": "必填项缺失"})
            if self.kind == "array":
                return []
            if self.kind == "object":
                return self._validate_object({})
            if self.kind == "boolean":
                return False
            return None
        if self._required and isinstance(value, str) and not value.strip():
            raise SchemaError({"": "必填项不能是空字符串"})
        if self.kind == "string":
            if not isinstance(value, str):
                raise SchemaError({"": "应为字符串，收到 %s" % type(value).__name__})
            return value
        if self.kind == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                raise SchemaError({"": "应为整数，收到 %s" % type(value).__name__})
            self._check_range(value)
            return value
        if self.kind == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise SchemaError({"": "应为数字，收到 %s" % type(value).__name__})
            self._check_range(value)
            return value
        if self.kind == "boolean":
            if not isinstance(value, bool):
                raise SchemaError({"": "应为布尔值，收到 %s" % type(value).__name__})
            return value
        if self.kind == "enum":
            if value not in self.choices:
                raise SchemaError({"": "取值必须是 %s 之一" % "/".join(map(str, self.choices))})
            return value
        if self.kind == "array":
            if not isinstance(value, list):
                raise SchemaError({"": "应为数组，收到 %s" % type(value).__name__})
            assert self.item is not None
            out, errors = [], {}
            for index, element in enumerate(value):
                try:
                    out.append(self.item.validate(element))
                except SchemaError as exc:
                    for key, text in exc.errors.items():
                        errors["[%d]%s" % (index, ("." + key) if key else "")] = text
            if errors:
                raise SchemaError(errors)
            return out
        if self.kind == "object":
            if not isinstance(value, dict):
                raise SchemaError({"": "应为对象，收到 %s" % type(value).__name__})
            return self._validate_object(value)
        raise SchemaError({"": "内核不认识的类型 %r" % self.kind})

    def _check_range(self, value: Any) -> None:
        if self._minimum is not None and value < self._minimum:
            raise SchemaError({"": "不能小于 %s" % self._minimum})
        if self._maximum is not None and value > self._maximum:
            raise SchemaError({"": "不能大于 %s" % self._maximum})

    def _validate_object(self, value: Dict[str, Any]) -> Dict[str, Any]:
        shape = self.shape or {}
        errors: Dict[str, str] = {}
        for key in value:
            if key not in shape:
                errors[key] = "未知配置项"
        out: Dict[str, Any] = {}
        for key, sub in shape.items():
            raw = value.get(key, _MISSING)
            try:
                out[key] = sub.validate(raw)
            except SchemaError as exc:
                if not exc.errors:
                    errors[key] = "校验失败"
                for sub_key, text in exc.errors.items():
                    errors[key + ("." + sub_key if sub_key else "")] = text
        if errors:
            raise SchemaError(errors)
        return out

    # ---- 导出给前端生成表单 ----

    def to_json_schema(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {}
        mapping = {
            "string": "string",
            "integer": "integer",
            "number": "number",
            "boolean": "boolean",
            "array": "array",
            "object": "object",
        }
        if self.kind == "enum":
            data["type"] = type(self.choices[0]).__name__ if self.choices else "string"
            if data["type"] == "int":
                data["type"] = "integer"
            data["enum"] = list(self.choices)
        else:
            data["type"] = mapping.get(self.kind, self.kind)
        if self._description:
            data["description"] = self._description
        if self.has_default:
            data["default"] = self.default_value
        if self._secret:
            data["x-secret"] = True
        if self._minimum is not None:
            data["minimum"] = self._minimum
        if self._maximum is not None:
            data["maximum"] = self._maximum
        if self.kind == "array" and self.item is not None:
            data["items"] = self.item.to_json_schema()
        if self.kind == "object":
            shape = self.shape or {}
            data["properties"] = {k: v.to_json_schema() for k, v in shape.items()}
            required = [k for k, v in shape.items() if v.is_required and not v.has_default]
            if required:
                data["required"] = required
            data["additionalProperties"] = False
        return data
