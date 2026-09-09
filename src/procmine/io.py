"""Loading dataset_a / dataset_b sessions from data/.

A "session" directory holds one or more "chunk" subdirectories (an artifact
of how the recording agent flushes data — see DATA_SCHEMA.md). Everything in
this module works at the session level and hides the chunk split from
callers: `iter_events(session_dir)` yields one continuous, time-ordered
event stream per session, regardless of how many chunk files it's stored
across.

Events are read with a streaming generator (line-by-line `json.loads`)
rather than "read whole file, `json.loads` a list" so that memory use stays
proportional to one event at a time, not to session size. For dataset_a's
~162k events this isn't strictly required (the data fits in RAM easily),
but it means the same code scales to much larger logs without changes.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator, Optional


def list_sessions(dataset_root: Path) -> list[Path]:
    """All session directories under a dataset root, sorted by name
    (session names start with a sortable date-time, so this is also
    chronological order)."""
    return sorted(p for p in dataset_root.iterdir() if p.is_dir() and p.name.startswith("ses_"))


def split_dev_test(sessions: list[Path], test_every: int = 5) -> tuple[list[Path], list[Path]]:
    """Deterministic dev/test split used throughout Step 1 evaluation
    (segmentation and labeling both use this exact split, so results are
    comparable across the two evaluation scripts). Every `test_every`-th
    session (by sorted/chronological order) goes to test; the held-out
    test sessions are only ever looked at once, after a configuration is
    already chosen on dev."""
    dev, test = [], []
    for i, s in enumerate(sessions):
        (test if i % test_every == test_every - 1 else dev).append(s)
    return dev, test


def load_manifest(chunk_dir: Path) -> dict:
    with open(chunk_dir / "manifest.json", encoding="utf-8") as f:
        return json.load(f)


def list_chunks(session_dir: Path) -> list[Path]:
    """Chunk directories for a session, ordered chronologically.

    We sort by each chunk's manifest `time_range.start_ms` rather than by
    directory name. In this data the names do happen to sort correctly, but
    relying on the manifest's own declared start time is the correct thing
    to depend on (it's the field whose job is to say when the chunk starts),
    not an assumption about naming.
    """
    chunk_dirs = [p for p in session_dir.iterdir() if p.is_dir() and p.name.startswith("chunk_")]

    def start_ms(chunk_dir: Path) -> int:
        return load_manifest(chunk_dir)["time_range"]["start_ms"]

    return sorted(chunk_dirs, key=start_ms)


def iter_events(session_dir: Path) -> Iterator[dict]:
    """Yield every event in a session, across all its chunks, in true
    chronological order (sorted by `timestamp_ms`).

    Within a chunk, events are NOT always written in timestamp order: ~6.7%
    of events in dataset_a have a negative `ms_since_last_event`, meaning
    the event before them in the file actually happened later. The worst
    observed case is a SYSTEM `upload_started` event whose timestamp is
    ~12 minutes ahead of the very next line in the file (a `screenshot_smart`
    event). This happens because SYSTEM-layer bookkeeping events (uploads)
    and L1 screenshot events are appended by different internal pipelines
    than the main L2/L3 event capture, and their write order doesn't always
    match their timestamp order.

    We therefore read each chunk fully and sort by `timestamp_ms` (stable
    sort, so same-millisecond events keep their file order) before
    yielding. This trades "fully streaming" for "correct order" at the
    per-chunk level — chunks here are at most a few thousand events, so
    holding one chunk in memory to sort it is cheap; we still avoid holding
    a whole multi-chunk session or the whole dataset in memory at once.
    """
    for chunk_dir in list_chunks(session_dir):
        events_path = chunk_dir / "events.jsonl"
        with open(events_path, encoding="utf-8") as f:
            chunk_events = [json.loads(line) for line in f if line.strip()]
        chunk_events.sort(key=lambda e: e["timestamp_ms"])
        yield from chunk_events


def load_gt(session_dir: Path) -> list[dict]:
    """Ground-truth event list for a session (dataset_a only). Returns []
    if the session has no gt.jsonl (dataset_b)."""
    gt_path = session_dir / "gt.jsonl"
    if not gt_path.exists():
        return []
    with open(gt_path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_gt_manifest(session_dir: Path) -> Optional[dict]:
    """Ground-truth summary for a session (dataset_a only). Returns None if
    the session has no gt_manifest.json (dataset_b)."""
    p = session_dir / "gt_manifest.json"
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)
