"""Read-only reporting and snapshot generation for the MTP tracker."""

from __future__ import annotations

import datetime as dt

from . import model
from .model import Tracker


SNAPSHOT_SCHEMA_VERSION = 1


def build_snapshot(
    tracker: Tracker,
    collected_at: dt.datetime | None = None,
) -> dict:
    """Build a complete reporting snapshot from an already-loaded Tracker.

    This function performs no network requests and makes no tracker changes.
    """
    if collected_at is None:
        collected_at = dt.datetime.now(dt.timezone.utc)

    if collected_at.tzinfo is None:
        raise ValueError("collected_at must be timezone-aware")

    timestamp = (
        collected_at.astimezone(dt.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )

    trainees, counts = tracker.trainees(status="all")

    trainee_records = []
    for trainee in trainees:
        record = trainee.as_dict()
        record["milestones"] = [
            milestone.as_dict()
            for milestone in tracker.milestones(trainee)
        ]
        trainee_records.append(record)

    status_counts = {
        label: counts.get(code, 0)
        for code, label in model.STATUS_OPTIONS.items()
    }
    status_counts["Other / No Data"] = counts.get("other", 0)

    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "collected_at": timestamp,
        "source": "writable.site MTP tracker",
        "summary": {
            "total_trainees": counts.get("all", 0),
            "status_counts": status_counts,
        },
        "structure": {
            "regions": dict(tracker.structure.regions),
            "teams": [
                dict(team) for team in tracker.structure.teams
            ],
        },
        "trainees": trainee_records,
    }
