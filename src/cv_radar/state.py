"""Atomic, idempotent JSONL persistence."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cv_radar.models import ResearchItem, RunRecord
from cv_radar.processing.dedupe import item_fingerprint


def _read_jsonl(path: Path, key: str) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return records
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                records[str(record[key])] = record
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                raise ValueError(f"invalid state record in {path}:{line_number}: {exc}") from exc
    return records


def _atomic_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)


class StateStore:
    def __init__(self, state_dir: str | Path) -> None:
        self.state_dir = Path(state_dir)
        self.seen_path = self.state_dir / "seen_items.jsonl"
        self.runs_path = self.state_dir / "runs.jsonl"

    def upsert_seen(self, items: list[ResearchItem]) -> None:
        records = _read_jsonl(self.seen_path, "fingerprint")
        now = datetime.now(UTC).isoformat()
        for item in items:
            fingerprint = item_fingerprint(item)
            serialized = item.model_dump(mode="json")
            existing = records.get(fingerprint)
            if existing and existing.get("item") == serialized:
                continue
            first_seen = (existing or {}).get("first_seen_at", now)
            records[fingerprint] = {
                "fingerprint": fingerprint,
                "first_seen_at": first_seen,
                "last_seen_at": now,
                "item": serialized,
            }
        _atomic_jsonl(self.seen_path, [records[key] for key in sorted(records)])

    def upsert_run(self, run: RunRecord) -> None:
        records = _read_jsonl(self.runs_path, "run_key")
        serialized = run.model_dump(mode="json")
        existing = records.get(run.run_key)
        outcome_keys = {
            "target_date",
            "fetched_count",
            "candidate_count",
            "report_count",
            "source_errors",
            "llm_enabled",
            "report_path",
        }
        if not existing or any(existing.get(key) != serialized.get(key) for key in outcome_keys):
            records[run.run_key] = serialized
        _atomic_jsonl(self.runs_path, [records[key] for key in sorted(records)])
