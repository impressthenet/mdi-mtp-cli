import pytest

from mtp_cli.comparison import compare_snapshots


def trainee(
    trainee_id,
    *,
    name=None,
    status="In progress",
    latest_date="2026-11-04",
    mentor="Mentor A",
    division="Division A",
    team="Team A",
    milestones=None,
):
    return {
        "id": trainee_id,
        "name": name or f"Trainee {trainee_id}",
        "status": status,
        "latestDate": latest_date,
        "mentor": mentor,
        "division": division,
        "team": team,
        "milestones": milestones or [],
    }


def snapshot(trainees, collected_at):
    return {
        "schema_version": 1,
        "collected_at": collected_at,
        "trainees": trainees,
    }


OLDER = "2026-10-01T12:00:00Z"
NEWER = "2026-11-04T12:00:00Z"


def test_detects_added_missing_and_changed_records():
    old = snapshot([
        trainee(1),
        trainee(2),
        trainee(3),
    ], OLDER)

    new = snapshot([
        trainee(1, mentor="Mentor B"),
        trainee(2, status="Completed program"),
        trainee(4),
    ], NEWER)

    result = compare_snapshots(old, new)

    assert result["totals"] == {
        "before": 3, "after": 3, "change": 0
    }
    assert result["records"]["added_count"] == 1
    assert result["records"]["added"][0]["id"] == 4
    assert result["records"]["missing_from_newer_count"] == 1
    assert result["records"]["missing_from_newer"][0]["id"] == 3
    assert result["records"]["changed_count"] == 2

    changes = {
        item["id"]: item["changes"]
        for item in result["records"]["changed"]
    }
    assert changes[1]["mentor"]["after"] == "Mentor B"
    assert changes[2]["status"]["after"] == "Completed program"


def test_detects_newly_completed_and_reversed_milestones():
    old = snapshot([
        trainee(1, milestones=[
            {"milestone": "Lead a group", "done": True},
            {"milestone": "Give a talk", "done": True},
        ]),
    ], OLDER)

    new = snapshot([
        trainee(1, milestones=[
            {"milestone": "Lead a group", "done": True},
            {"milestone": "Give a talk", "done": False},
            {"milestone": "Organize event", "done": True},
        ]),
    ], NEWER)

    result = compare_snapshots(old, new)
    changes = result["records"]["changed"][0]["changes"]

    assert changes["milestones"]["newly_completed"] == ["organize event"]
    assert changes["milestones"]["no_longer_completed"] == ["give a talk"]
    assert result["milestone_progress"]["completed_change"] == 0
    assert result["milestone_progress"]["total_change"] == 1


def test_inactivity_uses_each_snapshots_own_reference_date():
    old = snapshot([
        trainee(1, latest_date="2026-09-20"),
    ], OLDER)

    new = snapshot([
        trainee(1, latest_date="2026-09-20"),
    ], NEWER)

    result = compare_snapshots(old, new)

    assert result["records"]["changed_count"] == 0
    assert result["records"]["inactivity_changed_count"] == 1

    change = result["records"]["inactivity_changed"][0]
    assert change["before"]["days_since_activity"] == 11
    assert change["after"]["days_since_activity"] == 45
    assert change["before"]["band"] == "Current"
    assert change["after"]["band"] == "Attention"


def test_duplicate_ids_are_not_matched():
    old = snapshot([
        trainee(1),
        trainee(1, name="Second record"),
        trainee(2),
    ], OLDER)

    new = snapshot([
        trainee(1),
        trainee(2),
    ], NEWER)

    result = compare_snapshots(old, new)

    assert result["ambiguous_ids"]["older"] == ["1"]
    assert result["records"]["added_count"] == 1
    assert result["records"]["added"][0]["id"] == 1
    assert result["records"]["missing_from_newer_count"] == 0


def test_records_without_ids_are_counted_not_name_matched():
    old = snapshot([
        trainee(None, name="Same Name"),
    ], OLDER)

    new = snapshot([
        trainee(None, name="Same Name"),
    ], NEWER)

    result = compare_snapshots(old, new)

    assert result["records_without_ids"] == {
        "older": 1,
        "newer": 1,
    }
    assert result["records"]["changed_count"] == 0
    assert result["records"]["added_count"] == 0


def test_status_normalization_avoids_false_change():
    old = snapshot([
        trainee(1, status="no data"),
    ], OLDER)

    new = snapshot([
        trainee(1, status="Other / No Data"),
    ], NEWER)

    result = compare_snapshots(old, new)

    assert result["records"]["changed_count"] == 0


def test_invalid_snapshot_is_rejected():
    with pytest.raises(ValueError, match="schema version"):
        compare_snapshots(
            {"schema_version": 2},
            snapshot([], NEWER),
        )


def test_milestone_identity_uses_goal_id_for_duplicate_names():
    old = snapshot([
        trainee(1, milestones=[
            {"goalId": 10, "milestone": "Attend workshop", "done": True},
            {"goalId": 11, "milestone": "Attend workshop", "done": False},
        ]),
    ], OLDER)

    new = snapshot([
        trainee(1, milestones=[
            {"goalId": 10, "milestone": "Attend workshop", "done": True},
            {"goalId": 11, "milestone": "Attend workshop", "done": True},
        ]),
    ], NEWER)

    result = compare_snapshots(old, new)
    changes = result["records"]["changed"][0]["changes"]

    assert changes["milestones"]["newly_completed"] == ["attend workshop"]
    assert changes["milestones"]["no_longer_completed"] == []


def test_renamed_milestone_with_same_goal_id_is_not_a_new_completion():
    old = snapshot([
        trainee(1, milestones=[
            {"goalId": 42, "milestone": "Attend workshop", "done": True},
        ]),
    ], OLDER)

    new = snapshot([
        trainee(1, milestones=[
            {"goalId": 42, "milestone": "Participate in workshop", "done": True},
        ]),
    ], NEWER)

    result = compare_snapshots(old, new)

    assert result["records"]["changed_count"] == 0
