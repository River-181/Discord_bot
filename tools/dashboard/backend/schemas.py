from __future__ import annotations

from typing import Any


class APIDefaultError:
    message: str
    missing_files: list[str]
    corrupt_lines: int


def to_dict_record(record: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for field in fields:
        if field in record:
            payload[field] = record.get(field)
    return payload
