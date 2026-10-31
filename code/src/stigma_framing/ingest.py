import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Item:
    item_id: str
    fields: dict[str, str]
    input_hash: str
    source_row: int
    source_id: str
    metadata: dict


def load(path: Path, mapping: dict | None = None) -> list[Item]:
    mapping = mapping or {"item_id": "item_id", "title": "title", "abstract": "abstract"}
    if set(mapping) != {"item_id", "title", "abstract"}:
        raise ValueError("mapping requires item_id, title, abstract")
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not set(mapping.values()) <= set(reader.fieldnames or []):
                raise ValueError("missing required CSV fields")
            rows = list(reader)
    elif path.suffix.lower() == ".parquet":
        import pyarrow.parquet as pq
        table = pq.read_table(path)
        if not set(mapping.values()) <= set(table.column_names):
            raise ValueError("missing required Parquet fields")
        rows = table.to_pylist()
    else:
        raise ValueError("only CSV and Parquet inputs supported")
    result, seen = [], set()
    for index, row in enumerate(rows, 1):
        if None in row:
            raise ValueError(f"malformed CSV row {index}")
        source_id = row.get(mapping["item_id"])
        fields = {key: row.get(mapping[key]) for key in ("title", "abstract")}
        if not isinstance(source_id, str) or not source_id.strip() or source_id in seen:
            raise ValueError(f"missing/duplicate source ID at row {index}")
        if any(not isinstance(v, str) for v in fields.values()) or not any(v.strip() for v in fields.values()):
            raise ValueError(f"missing/non-text input at row {index}")
        seen.add(source_id)
        metadata = {k: v for k, v in row.items() if k not in mapping.values()}
        result.append(Item("local-" + digest(source_id)[:20], fields, digest(fields),
                           index, source_id, metadata))
    return result
