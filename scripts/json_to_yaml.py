"""
JSON -> YAML 转换脚本
- 按 `normalize_item_meta_flat_fields.yaml` 的字段定义强制类型
- 自动补全缺失字段：string -> ""，number -> null，boolean -> false，array -> []
- 字符串统一用双引号输出
- 输入支持两种形式：
  1) 完整 JSON 对象
  2) `data` 对象内部字段片段（不带最外层 `{}`）
- 输出直接打印到终端，不写文件
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import yaml


if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


class QuotedStr(str):
    pass


def quoted_str_representer(dumper: yaml.Dumper, data: QuotedStr):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='"')


def none_representer(dumper: yaml.Dumper, data: None):
    return dumper.represent_scalar("tag:yaml.org,2002:null", "null")


yaml.add_representer(QuotedStr, quoted_str_representer)
yaml.add_representer(type(None), none_representer)


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
SCHEMA_PATH = os.path.join(PROJECT_ROOT, "normalize_item_meta_flat_fields.yaml")

TOP_FIELD_TYPES: dict[str, str] = {}
LOT_PRODUCT_FIELD_TYPES: dict[str, str] = {}
LOT_CANDIDATE_FIELD_TYPES: dict[str, str] = {}


def _load_schema() -> None:
    with open(SCHEMA_PATH, "r", encoding="utf-8") as file:
        schema = yaml.safe_load(file) or {}

    for field in schema.get("fields", []):
        key = field.get("key", "")
        field_type = field.get("type", "string")
        if key:
            TOP_FIELD_TYPES[key] = field_type

    LOT_PRODUCT_FIELD_TYPES.update(
        {
            "lotNumber": "string",
            "lotName": "string",
            "subjects": "string",
            "productCategory": "string",
            "models": "string",
            "unitPrices": "number",
            "quantities": "string",
            "quantityUnit": "string",
        }
    )
    LOT_CANDIDATE_FIELD_TYPES.update(
        {
            "lotNumber": "string",
            "lotName": "string",
            "type": "string",
            "candidates": "string",
            "candidatePrices": "number",
        }
    )


_load_schema()


TYPE_DEFAULTS: dict[str, Any] = {
    "string": "",
    "number": None,
    "boolean": False,
    "array": [],
}


def _coerce(value: Any, field_type: str):
    if field_type == "string":
        if value is None:
            return QuotedStr("")
        return QuotedStr(str(value))

    if field_type == "number":
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.lower() in {"", "null", "none"}:
                return None
            value = stripped.replace(",", "")
        try:
            if isinstance(value, (int, float)):
                return value
            return float(value) if "." in str(value) else int(value)
        except (ValueError, TypeError):
            return None

    if field_type == "boolean":
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        if isinstance(value, str):
            return value.strip().lower() in {"true", "1", "yes", "是"}
        return bool(value)

    return value


def _coerce_lot_item(item: dict[str, Any], field_types: dict[str, str]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, field_type in field_types.items():
        value = item.get(key, TYPE_DEFAULTS.get(field_type, ""))
        output[key] = _coerce(value, field_type)
    return output


def _build_output(data: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, field_type in TOP_FIELD_TYPES.items():
        value = data.get(key, TYPE_DEFAULTS.get(field_type, ""))
        if field_type == "array":
            raw_list = data.get(key) if isinstance(data.get(key), list) else []
            if key == "lotProducts":
                output[key] = [
                    _coerce_lot_item(item, LOT_PRODUCT_FIELD_TYPES)
                    for item in raw_list
                    if isinstance(item, dict)
                ]
            elif key == "lotCandidates":
                output[key] = [
                    _coerce_lot_item(item, LOT_CANDIDATE_FIELD_TYPES)
                    for item in raw_list
                    if isinstance(item, dict)
                ]
            else:
                output[key] = raw_list
        else:
            output[key] = _coerce(value, field_type)
    return output


def _parse_input_json(raw: str) -> dict[str, Any]:
    stripped = raw.strip()
    candidates = [stripped]

    if stripped and not stripped.startswith("{"):
        candidates.append("{" + stripped + "}")

    last_error: Exception | None = None
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue

        if not isinstance(data, dict):
            raise SystemExit("输入必须是 JSON 对象")

        if "data" in data and isinstance(data["data"], dict):
            data = data["data"]
        return data

    raise SystemExit(f"JSON 解析失败: {last_error}")


def main() -> int:
    if len(sys.argv) > 1:
        with open(sys.argv[1], "r", encoding="utf-8") as file:
            raw = file.read()
    else:
        raw = sys.stdin.read()

    raw = raw.strip()
    if not raw:
        raise SystemExit("输入为空")

    data = _parse_input_json(raw)
    output = _build_output(data)
    yaml_text = yaml.dump(output, allow_unicode=True, default_flow_style=False, sort_keys=False)
    print(yaml_text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
