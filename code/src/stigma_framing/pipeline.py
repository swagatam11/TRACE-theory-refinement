import json
import platform
import time
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from pydantic import TypeAdapter

from .ingest import digest, load
from .schema import Annotation, Unit, verify, verify_units


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def run(input_path, output, method, codebook_path, prompt_dir, client, max_items=50):
    if method not in ("direct", "evidence_first"):
        raise ValueError("unknown method")
    items = load(input_path)
    if len(items) > max_items or max_items < 1:
        raise ValueError("input exceeds explicit item cap; no rows processed")
    codebook = json.loads(codebook_path.read_text(encoding="utf-8"))
    stages = ["direct"] if method == "direct" else ["extract", "judge"]
    prompts = {s: (prompt_dir / f"{s}.txt").read_text(encoding="utf-8") for s in stages}
    code_hash = digest({p.name: p.read_text(encoding="utf-8") for p in sorted(Path(__file__).parent.glob("*.py"))})
    provenance = {"schema_version": "0.1", "codebook_version": codebook["version"],
                  "codebook_hash": digest(codebook), "prompt_hash": digest(prompts),
                  "model": client.model_id, "fixture_hash": client.fixture_hash,
                  "method": method, "code_hash": code_hash, "settings": {"concurrency": 1, "max_attempts": 3},
                  "python": platform.python_version(), "pydantic": version("pydantic"),
                  "pyarrow": version("pyarrow") if input_path.suffix.lower() == ".parquet" else None}
    run_id = digest({"provenance": provenance,
                     "inputs": [(i.item_id, i.input_hash, i.source_row) for i in items]})[:24]
    records, seen = [], set()
    coordinator = []
    for item in items:
        coordinator.append({"local_id": item.item_id, "source_id": item.source_id,
                            "source_row": item.source_row, "metadata": item.metadata})
        duplicate = item.input_hash in seen
        seen.add(item.input_hash)
        record = {"run_id": run_id, "item_id": item.item_id, "input_hash": item.input_hash,
                  "raw_fields": item.fields, "source": {"filename": input_path.name, "row": item.source_row},
                  "duplicate_text": duplicate, "provenance": provenance, "status": "error",
                  "annotation": None, "error": None, "ledger": [], "v2_anchoring": None}
        extracted = None
        try:
            for stage in stages:
                request = {"input_hash": item.input_hash, "fields": item.fields, "stage": stage,
                           "prompt": prompts[stage], "codebook": codebook,
                           "extracted_units": extracted}
                key = digest({"request": request, "provenance": provenance})
                raw_path = output / "cache" / f"{key}.json"
                cached = raw_path.exists()
                start = time.perf_counter()
                attempts = 0
                if cached:
                    envelope = json.loads(raw_path.read_text(encoding="utf-8"))
                    if envelope["request_hash"] != digest(request):
                        raise ValueError("cache request mismatch")
                    raw = envelope["response"]
                else:
                    for attempts in range(1, 4):
                        try:
                            raw = client.complete(request)
                            break
                        except (TimeoutError, ConnectionError):
                            if attempts == 3:
                                raise
                            time.sleep(0.01 * 2 ** (attempts - 1))
                    save(raw_path, {"request_hash": digest(request), "request": request, "response": raw})
                record["ledger"].append({"stage": stage, "cache_key": key, "cache_hit": cached,
                                          "attempts": attempts, "cost_usd": 0, "tokens": None,
                                          "latency_seconds": time.perf_counter() - start})
                if stage == "extract":
                    units = TypeAdapter(list[Unit]).validate_json(raw)
                    verify_units(units, item.fields, codebook)
                    extracted = [u.model_dump() for u in units]
                else:
                    annotation = Annotation.model_validate_json(raw)
                    verify(annotation, item.fields, codebook)
                    if stage == "judge" and [u.model_dump() for u in annotation.units] != extracted:
                        raise ValueError("judge changed extracted evidence units")
                    record["annotation"] = annotation.model_dump()
                    save(output / "parsed" / f"{key}.json", annotation.model_dump())
            record["status"] = "ok"
        except (ValueError, KeyError, TimeoutError, ConnectionError) as exc:
            if not record["ledger"] or record["ledger"][-1]["stage"] != stage:
                record["ledger"].append({"stage": stage, "cache_key": key, "cache_hit": cached,
                    "attempts": attempts, "cost_usd": 0, "tokens": None,
                    "latency_seconds": time.perf_counter() - start, "failure": type(exc).__name__})
            record["annotation"] = None
            record["error"] = {"type": type(exc).__name__, "message": str(exc)}
        records.append(record)
        save(output / method / "checkpoints" / f"{item.item_id}.json", record)
    save(output / method / "annotations.json", records)
    save(output / method / "coordinator.json", coordinator)
    save(output / method / "manifest.json", {"run_id": run_id, "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_file_hash": __import__("hashlib").sha256(input_path.read_bytes()).hexdigest(),
        "items": len(items), "errors": sum(r["status"] == "error" for r in records),
        "cost_usd": 0, "warning": "MOCK ONLY. v2 baseline unavailable; no semantic validation.",
        "provenance": provenance})
    return records
