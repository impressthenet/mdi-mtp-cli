import datetime as dt

import pytest

from mtp_cli.analysis import analyze_snapshot


REFERENCE_DATE = dt.date(2026, 11, 4)


def trainee(
    trainee_id,
    *,
    status="In progress",
    days_ago=None,
    division="Division A",
    team="Team A",
    mentor="Mentor A",
    milestones=None,
):
    latest_date = None
    if days_ago is not None:
        latest_date = (
            REFERENCE_DATE - dt.timedelta(days=days_ago)
        ).isoformat()

    return {
        "id": trainee_id,
        "name": f"Trainee {trainee_id}",
        "status": status,
        "division": division,
        "team": team,
        "mentor": mentor,
        "latestDate": latest_date,
        "milestones": milestones or [],
    }


def snapshot(trainees):
    return {
        "schema_version": 1,
        "collected_at": "2026-11-04T23:18:43Z",
        "trainees": trainees,
    }


def test_inactivity_boundaries():
    records = [
        trainee(1, days_ago=0),
        trainee(2, days_ago=29),
        trainee(3, days_ago=30),
        trainee(4, days_ago=59),
        trainee(5, days_ago=60),
        trainee(6, days_ago=89),
        trainee(7, days_ago=90),
        trainee(8, days_ago=None),
        {
            **trainee(9),
            "latestDate": "not-a-date",
        },
        {
            **trainee(10),
            "latestDate": "2026-11-05",
        },
    ]

    result = analyze_snapshot(snapshot(records))

    assert result["inactivity_counts"] == {
        "Current": 2,
        "Attention": 2,
        "Stalled": 2,
        "Extended": 1,
        "Unknown": 2,
        "Future": 1,
    }

    assert result["data_quality"]["missing_latest_date"] == 1
    assert result["data_quality"]["malformed_latest_date"] == 1
    assert result["data_quality"]["future_latest_date"] == 1


def test_division_and_team_milestone_totals_are_independent():
    records = [
        trainee(
            1,
            division="Shared",
            team="Shared",
            milestones=[
                {"done": True},
                {"done": False},
            ],
        ),
        trainee(
            2,
            division="Shared",
            team="Different Team",
            milestones=[
                {"done": True},
            ],
        ),
        trainee(
            3,
            division="Different Division",
            team="Shared",
            milestones=[
                {"done": False},
                {"done": False},
                {"done": False},
            ],
        ),
    ]

    result = analyze_snapshot(snapshot(records))

    assert result["division_summary"]["Shared"]["milestones_done"] == 2
    assert result["division_summary"]["Shared"]["milestones_total"] == 3

    assert result["team_summary"]["Shared"]["milestones_done"] == 1
    assert result["team_summary"]["Shared"]["milestones_total"] == 5


def test_no_data_status_is_normalized():
    result = analyze_snapshot(snapshot([
        trainee(1, status="no data"),
        trainee(2, status="Other / No Data"),
    ]))

    assert result["status_counts"] == {"Other / No Data": 2}


def test_attention_lists_and_mentor_summary():
    records = [
        trainee(1, days_ago=95, mentor="Mentor A"),
        trainee(2, days_ago=45, mentor="Mentor A"),
        trainee(3, days_ago=10, mentor="Mentor B"),
        trainee(4, days_ago=95, mentor=None),
    ]

    result = analyze_snapshot(snapshot(records))

    assert [item["id"] for item in result["inactivity_trainees"]["Extended"]] == [1, 4]
    assert result["inactivity_trainees"]["Attention"][0]["id"] == 2

    mentor_a = result["mentor_attention_summary"]["Mentor A"]
    assert mentor_a["total_in_progress"] == 2
    assert mentor_a["inactivity"]["Extended"] == 1
    assert mentor_a["inactivity"]["Attention"] == 1

    unassigned = result["mentor_attention_summary"]["Unassigned"]
    assert unassigned["total_in_progress"] == 1
    assert unassigned["inactivity"]["Extended"] == 1


def test_duplicate_ids_are_counted():
    result = analyze_snapshot(snapshot([
        trainee(1),
        trainee(1),
        trainee(2),
    ]))

    assert result["data_quality"]["duplicate_trainee_ids"] == 1


def test_invalid_snapshot_is_rejected():
    with pytest.raises(ValueError, match="schema version"):
        analyze_snapshot({"schema_version": 2})

    with pytest.raises(ValueError, match="collected_at"):
        analyze_snapshot({
            "schema_version": 1,
            "collected_at": "not-a-timestamp",
            "trainees": [],
        })

    with pytest.raises(ValueError, match="trainees"):
        analyze_snapshot({
            "schema_version": 1,
            "collected_at": "2026-11-04T23:18:43Z",
            "trainees": {},
        })


def test_duplicate_review_marks_user_confirmed_steve_geer():
    first = {
        **trainee(1, status="Completed program",
                  division="West Bay", team="Rising Phoenix",
                  mentor="Beale", milestones=[
                      {"milestone": "Lead Fun", "done": True},
                      {"milestone": "Teach", "done": True},
                  ]),
        "name": "Geer, Steve",
        "id": "/u/bealewestbay/posts/89",
    }
    second = {
        **trainee(2, status="Left before completing",
                  division="West Bay", team="Ocean Kings",
                  mentor=None, milestones=[
                      {"milestone": "Lead Fun", "done": True},
                  ]),
        "name": "Steve Geer",
        "id": "/u/Illyafee/posts/166",
    }

    result = analyze_snapshot(snapshot([first, second]))
    review = result["duplicate_review"]

    assert review["repeated_name_groups"] == 1
    assert review["records_in_groups"] == 2
    group = review["groups"][0]
    assert group["confidence"] == "Confirmed"
    assert group["record_count"] == 2
    assert "User-confirmed: both records represent Steve Geer" in (
        group["comparisons"][0]["evidence"]
    )


def test_duplicate_review_confidence_uses_record_evidence():
    records = [
        {
            **trainee(1, division="Same Division", team="Same Team"),
            "name": "Example Person",
            "id": "/u/example/posts/1",
            "milestones": [
                {"milestone": f"Milestone {n}", "done": True}
                for n in range(4)
            ],
        },
        {
            **trainee(2, division="Same Division", team="Same Team"),
            "name": " example   person ",
            "id": "/u/example/posts/2",
            "milestones": [
                {"milestone": f"Milestone {n}", "done": True}
                for n in range(4)
            ],
        },
        {
            **trainee(3, division="Other Division", team="Other Team"),
            "name": "EXAMPLE PERSON",
            "id": "/u/another/posts/3",
            "milestones": [],
        },
    ]

    review = analyze_snapshot(snapshot(records))["duplicate_review"]
    assert review["repeated_name_groups"] == 1
    assert review["records_in_groups"] == 3
    group = review["groups"][0]

    # Group confidence reflects the weakest pair in the group.
    assert group["confidence"] == "Low"
    assert len(group["records"]) == 3

    pair_confidences = [
        comparison["confidence"]
        for comparison in group["comparisons"]
    ]
    assert pair_confidences.count("High") == 1
    assert pair_confidences.count("Low") == 2

def test_duplicate_review_low_confidence_for_name_only_match():
    records = [
        {**trainee(1, division="Division A", team="Team A"),
         "name": "Jordan Example", "id": "/u/one/posts/1"},
        {**trainee(2, division="Division B", team="Team B"),
         "name": "Jordan Example", "id": "/u/two/posts/2"},
    ]

    review = analyze_snapshot(snapshot(records))["duplicate_review"]
    assert review["groups"][0]["confidence"] == "Low"


def test_duplicate_review_does_not_modify_snapshot():
    import copy

    records = [
        {**trainee(1), "name": "Same Name"},
        {**trainee(2), "name": "Same Name"},
    ]
    original = copy.deepcopy(records)

    analyze_snapshot(snapshot(records))

    assert records == original


def test_duplicate_review_ignores_blank_names_and_unique_names():
    records = [
        {**trainee(1), "name": ""},
        {**trainee(2), "name": "   "},
        {**trainee(3), "name": "Only Person"},
    ]

    review = analyze_snapshot(snapshot(records))["duplicate_review"]
    assert review["repeated_name_groups"] == 0
    assert review["records_in_groups"] == 0
    assert review["groups"] == []


def test_manual_duplicate_confirmation_does_not_apply_to_other_records():
    first = {
        **trainee(
            1,
            status="Completed program",
            division="West Bay",
            team="Rising Phoenix",
            mentor="Beale",
            milestones=[
                {"milestone": "Lead Fun", "done": True},
            ],
        ),
        "name": "Geer, Steve",
        "id": "/u/another/posts/89",
    }
    second = {
        **trainee(
            2,
            status="Left before completing",
            division="Atlantic",
            team="Other Team",
            mentor=None,
            milestones=[],
        ),
        "name": "Steve Geer",
        "id": "/u/other/posts/166",
    }

    result = analyze_snapshot(snapshot([first, second]))
    review = result["duplicate_review"]

    assert review["repeated_name_groups"] == 1
    assert review["records_in_groups"] == 2

    group = review["groups"][0]
    assert group["confidence"] == "Low"

    evidence = group["comparisons"][0]["evidence"]
    assert not any(
        item.startswith("User-confirmed:")
        for item in evidence
    )


def test_latest_date_rejects_valid_date_with_trailing_text():
    records = [
        {
            **trainee(1),
            "latestDate": "2026-11-04garbage",
        },
        {
            **trainee(2),
            "latestDate": "2026-11-04T12:00:00",
        },
    ]

    result = analyze_snapshot(snapshot(records))

    assert result["data_quality"]["malformed_latest_date"] == 2
    assert result["data_quality"]["missing_latest_date"] == 0
    assert result["inactivity_counts"]["Unknown"] == 2


def test_duplicate_id_detection_handles_unhashable_ids():
    records = [
        {**trainee(1), "id": ["unexpected", "list"]},
        {**trainee(2), "id": ["unexpected", "list"]},
        trainee(3),
    ]

    result = analyze_snapshot(snapshot(records))

    assert result["data_quality"]["duplicate_trainee_ids"] == 1
    assert result["inactivity_trainees"]["Unknown"][0]["id"] == [
        "unexpected", "list"
    ]


def test_snapshot_must_be_a_json_object():
    with pytest.raises(ValueError, match="JSON object"):
        analyze_snapshot([])

    with pytest.raises(ValueError, match="JSON object"):
        analyze_snapshot(None)


def test_snapshot_rejects_non_object_trainee():
    with pytest.raises(ValueError, match="trainee at index 0"):
        analyze_snapshot(snapshot(["not a trainee"]))


def test_snapshot_rejects_invalid_milestone_structure():
    with pytest.raises(ValueError, match="milestones must be a list"):
        analyze_snapshot(snapshot([
            {**trainee(1), "milestones": "not a list"},
        ]))

    with pytest.raises(ValueError, match="milestone 0 must be an object"):
        analyze_snapshot(snapshot([
            {**trainee(1), "milestones": ["not a milestone"]},
        ]))


def test_snapshot_rejects_timestamp_without_timezone():
    with pytest.raises(ValueError, match="collected_at"):
        analyze_snapshot({
            "schema_version": 1,
            "collected_at": "2026-11-04T23:18:43",
            "trainees": [],
        })
