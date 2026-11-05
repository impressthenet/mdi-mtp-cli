"""Offline analysis of saved MTP reporting snapshots."""

from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict


INACTIVITY_BANDS = (
    ("Current", 0, 29),
    ("Attention", 30, 59),
    ("Stalled", 60, 89),
    ("Extended", 90, None),
)

INACTIVITY_LABELS = (
    "Current", "Attention", "Stalled", "Extended", "Unknown", "Future"
)


# Explicit human decisions, keyed by the exact pair of tracker record IDs.
# These decisions affect review labels only; records are never merged.
MANUALLY_CONFIRMED_DUPLICATES = {
    frozenset({
        "/u/bealewestbay/posts/89",
        "/u/Illyafee/posts/166",
    }): "User-confirmed: both records represent Steve Geer",
}


def _parse_date(value):
    if not value:
        return None
    if not isinstance(value, str):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def _normalize_status(value):
    """Normalize the tracker's no-data status without changing other labels."""
    status = value or "Other / No Data"
    if status.strip().casefold() in {"no data", "other / no data"}:
        return "Other / No Data"
    return status


def _inactivity_band(latest_date, reference_date):
    if latest_date is None:
        return "Unknown", None

    days = (reference_date - latest_date).days
    if days < 0:
        return "Future", days

    for name, lower, upper in INACTIVITY_BANDS:
        if days >= lower and (upper is None or days <= upper):
            return name, days

    return "Unknown", days



def _duplicate_review(trainees):
    """Identify repeated-name records for human review; never merge them."""
    grouped = defaultdict(list)

    def normalized_name(record):
        name = record.get("name") or " ".join(
            part for part in (
                record.get("firstName") or "",
                record.get("lastName") or "",
            ) if part
        )
        # Ignore capitalization, whitespace, comma placement, and
        # first-name/last-name order. This is a review grouping only.
        parts = name.replace(",", " ").casefold().split()
        return " ".join(sorted(parts))

    def account_path(record):
        trainee_id = str(record.get("id") or "")
        if "/posts/" in trainee_id:
            return trainee_id.split("/posts/", 1)[0]
        return None

    def completed_milestones(record):
        return {
            str(item.get("milestone") or "").strip().casefold()
            for item in (record.get("milestones") or [])
            if item.get("done") and item.get("milestone")
        }

    for record in trainees:
        key = normalized_name(record)
        if key:
            grouped[key].append(record)

    groups = []
    for key, records in sorted(grouped.items()):
        if len(records) < 2:
            continue

        comparisons = []
        pair_confidences = []

        for index, first in enumerate(records):
            for second in records[index + 1:]:
                evidence = []
                first_milestones = completed_milestones(first)
                second_milestones = completed_milestones(second)
                shared = sorted(first_milestones & second_milestones)
                first_only = sorted(first_milestones - second_milestones)
                second_only = sorted(second_milestones - first_milestones)

                same_division = (
                    bool(first.get("division"))
                    and first.get("division") == second.get("division")
                )
                same_team = (
                    bool(first.get("team"))
                    and first.get("team") == second.get("team")
                )
                same_mentor = (
                    bool(first.get("mentor"))
                    and first.get("mentor") == second.get("mentor")
                )
                first_account = account_path(first)
                same_account = (
                    bool(first_account)
                    and first_account == account_path(second)
                )

                if same_division:
                    evidence.append("Same division")
                if same_team:
                    evidence.append("Same team")
                if same_mentor:
                    evidence.append("Same mentor")
                if same_account:
                    evidence.append("Same tracker account path")
                evidence.append(
                    f"{len(shared)} shared completed milestone(s)"
                )
                if shared:
                    evidence.append(
                        "Shared milestones: " + ", ".join(shared)
                    )
                if first_only or second_only:
                    evidence.append(
                        f"Milestones unique to first/second record: "
                        f"{len(first_only)}/{len(second_only)}"
                    )

                # Exact manually confirmed pairs take precedence over heuristics.
                first_id = first.get("id")
                second_id = second.get("id")

                manual_confirmation = None
                if first_id and second_id:
                    pair_ids = frozenset({
                        str(first_id),
                        str(second_id),
                    })
                    manual_confirmation = (
                        MANUALLY_CONFIRMED_DUPLICATES.get(pair_ids)
                    )

                if manual_confirmation:
                    confidence = "Confirmed"
                    evidence.append(manual_confirmation)
                elif (
                    same_division and same_team and len(shared) >= 3
                ) or (
                    same_account and len(shared) >= 3
                ):
                    confidence = "High"
                elif (
                    (same_division and same_team)
                    or same_account
                    or len(shared) >= 1
                ):
                    confidence = "Review"
                else:
                    confidence = "Low"

                pair_confidences.append(confidence)

                def record_summary(record):
                    return {
                        "id": record.get("id"),
                        "name": record.get("name") or key,
                        "division": record.get("division"),
                        "team": record.get("team"),
                        "status": record.get("status"),
                        "mentor": record.get("mentor"),
                        "latest_date": record.get("latestDate"),
                        "completed_milestones": len(
                            completed_milestones(record)
                        ),
                    }

                comparisons.append({
                    "first": record_summary(first),
                    "second": record_summary(second),
                    "confidence": confidence,
                    "evidence": evidence,
                })

        rank = {
            "Low": 0, "Review": 1, "High": 2, "Confirmed": 3
        }
        group_confidence = min(
            pair_confidences, key=lambda value: rank[value]
        )

        groups.append({
            "name": records[0].get("name") or key,
            "record_count": len(records),
            "confidence": group_confidence,
            "records": [
                {
                    "id": record.get("id"),
                    "name": record.get("name") or key,
                    "division": record.get("division"),
                    "team": record.get("team"),
                    "status": record.get("status"),
                    "mentor": record.get("mentor"),
                    "latest_date": record.get("latestDate"),
                    "completed_milestones": len(
                        completed_milestones(record)
                    ),
                }
                for record in records
            ],
            "comparisons": comparisons,
        })

    return {
        "repeated_name_groups": len(groups),
        "records_in_groups": sum(
            group["record_count"] for group in groups
        ),
        "groups": groups,
    }


def analyze_snapshot(snapshot: dict) -> dict:
    """Analyze a saved snapshot without network access or tracker changes."""
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot must be a JSON object")

    if snapshot.get("schema_version") != 1:
        raise ValueError("unsupported snapshot schema version")

    timestamp = snapshot.get("collected_at")
    if not isinstance(timestamp, str):
        raise ValueError(
            "snapshot has an invalid collected_at timestamp"
        )

    try:
        collected_at = dt.datetime.fromisoformat(
            timestamp.replace("Z", "+00:00")
        )
        if (
            collected_at.tzinfo is None
            or collected_at.utcoffset() is None
        ):
            raise ValueError
        reference_date = collected_at.date()
    except (TypeError, ValueError):
        raise ValueError(
            "snapshot has an invalid collected_at timestamp"
        ) from None

    trainees = snapshot.get("trainees")
    if not isinstance(trainees, list):
        raise ValueError("snapshot trainees must be a list")

    for index, trainee in enumerate(trainees):
        if not isinstance(trainee, dict):
            raise ValueError(
                f"snapshot trainee at index {index} must be an object"
            )

        milestones = trainee.get("milestones")
        if milestones is None:
            continue
        if not isinstance(milestones, list):
            raise ValueError(
                f"snapshot trainee at index {index} milestones must be a list"
            )
        for milestone_index, milestone in enumerate(milestones):
            if not isinstance(milestone, dict):
                raise ValueError(
                    f"snapshot trainee at index {index} milestone "
                    f"{milestone_index} must be an object"
                )

    status_counts = Counter()
    division_counts = defaultdict(Counter)
    team_counts = defaultdict(Counter)
    division_progress = defaultdict(lambda: [0, 0])
    team_progress = defaultdict(lambda: [0, 0])

    mentor_active = Counter()
    mentor_attention = defaultdict(Counter)
    inactivity_counts = Counter()
    inactivity_trainees = {name: [] for name in INACTIVITY_LABELS}

    missing_mentor = 0
    missing_latest_date = 0
    future_latest_date = 0
    malformed_latest_date = 0
    data_entry_errors = 0
    duplicate_ids = 0
    seen_ids = set()

    for trainee in trainees:
        status = _normalize_status(trainee.get("status"))
        division = trainee.get("division") or "Unassigned"
        team = trainee.get("team") or "Unassigned"
        mentor = trainee.get("mentor") or "Unassigned"

        status_counts[status] += 1
        division_counts[division][status] += 1
        team_counts[team][status] += 1

        trainee_id = trainee.get("id")
        if trainee_id is not None:
            id_key = str(trainee_id)
            if id_key in seen_ids:
                duplicate_ids += 1
            else:
                seen_ids.add(id_key)

        if not trainee.get("mentor"):
            missing_mentor += 1

        latest_raw = trainee.get("latestDate")
        latest_date = _parse_date(latest_raw)

        if not latest_raw:
            missing_latest_date += 1
        elif latest_date is None:
            malformed_latest_date += 1
        elif latest_date > reference_date:
            future_latest_date += 1

        milestones = trainee.get("milestones") or []
        completed = sum(bool(m.get("done")) for m in milestones)
        total = len(milestones)

        division_progress[division][0] += completed
        division_progress[division][1] += total
        team_progress[team][0] += completed
        team_progress[team][1] += total

        data_entry_errors += sum(
            bool(m.get("dataEntryError")) for m in milestones
        )

        if status != "In progress":
            continue

        band, days = _inactivity_band(latest_date, reference_date)
        inactivity_counts[band] += 1
        mentor_active[mentor] += 1
        mentor_attention[mentor][band] += 1

        first_name = trainee.get("firstName") or ""
        last_name = trainee.get("lastName") or ""
        name = trainee.get("name") or " ".join(
            part for part in (first_name, last_name) if part
        ) or "Unnamed trainee"

        inactivity_trainees[band].append({
            "id": trainee_id,
            "name": name,
            "division": division,
            "team": team,
            "mentor": mentor,
            "latest_date": latest_raw,
            "days_since_activity": days,
        })

    def group_summary(groups, progress):
        result = {}
        for name, counts in sorted(groups.items()):
            done, total = progress[name]
            result[name] = {
                "trainees": sum(counts.values()),
                "in_progress": counts.get("In progress", 0),
                "completed_program": counts.get("Completed program", 0),
                "milestones_done": done,
                "milestones_total": total,
                "milestone_completion_percent": (
                    round(100 * done / total, 1) if total else None
                ),
                "statuses": dict(sorted(counts.items())),
            }
        return result

    for band in INACTIVITY_LABELS:
        inactivity_trainees[band].sort(
            key=lambda item: (
                item["days_since_activity"] is None,
                -(item["days_since_activity"] or 0),
                item["name"].casefold(),
            )
        )

    mentor_attention_summary = {}
    for mentor, counts in sorted(
        mentor_attention.items(),
        key=lambda item: (-sum(item[1].values()), item[0].casefold()),
    ):
        mentor_attention_summary[mentor] = {
            "total_in_progress": sum(counts.values()),
            "inactivity": {
                band: counts.get(band, 0) for band in INACTIVITY_LABELS
            },
        }

    return {
        "reference_date": reference_date.isoformat(),
        "total_trainees": len(trainees),
        "status_counts": dict(sorted(status_counts.items())),
        "inactivity_counts": {
            band: inactivity_counts.get(band, 0)
            for band in INACTIVITY_LABELS
        },
        "inactivity_trainees": inactivity_trainees,
        "division_summary": group_summary(
            division_counts, division_progress
        ),
        "team_summary": group_summary(team_counts, team_progress),
        "active_mentor_workload": dict(
            sorted(
                mentor_active.items(),
                key=lambda item: (-item[1], item[0].casefold()),
            )
        ),
        "mentor_attention_summary": mentor_attention_summary,
        "duplicate_review": _duplicate_review(trainees),
        "data_quality": {
            "missing_mentor": missing_mentor,
            "missing_latest_date": missing_latest_date,
            "future_latest_date": future_latest_date,
            "malformed_latest_date": malformed_latest_date,
            "milestone_data_entry_errors": data_entry_errors,
            "duplicate_trainee_ids": duplicate_ids,
        },
    }
