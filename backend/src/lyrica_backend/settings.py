"""Shared UI/backend bounds and defaults, without analysis dependencies."""
import json
import math
from pathlib import Path

SCHEMA = json.loads(Path(__file__).with_name("settings.json").read_text(encoding="utf-8"))
DEFAULTS = {key: rule["default"] for group in SCHEMA.values() for key, rule in group.items()}


def analysis_options(value=None):
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError("解析設定はオブジェクトで指定してください")
    options = {**DEFAULTS, **value}
    for key, rule in SCHEMA["numeric"].items():
        number = options[key]
        if (isinstance(number, bool) or not isinstance(number, (int, float))
                or not math.isfinite(number) or not rule["min"] <= number <= rule["max"]
                or (rule["step"] == 1 and int(number) != number)):
            raise ValueError(f'{rule["label"]}は{rule["min"]}〜{rule["max"]}の範囲で指定してください')
        if rule["step"] == 1:
            options[key] = int(number)
    for key, rule in SCHEMA["boolean"].items():
        if not isinstance(options[key], bool):
            raise ValueError(f'{rule["label"]}はオンまたはオフで指定してください')
    if options["review_agreement"] < options["min_agreement"]:
        raise ValueError("要確認にする一致率は、時刻採用に必要な一致率以上にしてください")
    return options
