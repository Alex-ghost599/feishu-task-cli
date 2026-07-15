from feishu_task_cli.application.reconcile import reconcile


def test_reconcile_reports_match_mismatch_and_omission() -> None:
    result = reconcile(
        {"summary": "Expected", "completed_at": "123", "description": "Required"},
        {"summary": "Expected", "completed_at": "456"},
    )

    assert result.mismatches == ("completed_at",)
    assert result.omitted_fields == ("description",)
    assert not result.verified


def test_reconcile_is_verified_when_all_requested_fields_match() -> None:
    result = reconcile({"summary": "Expected"}, {"summary": "Expected", "extra": True})
    assert result.verified
    assert result.mismatches == ()
    assert result.omitted_fields == ()


def test_reconcile_treats_requested_assignees_as_order_independent_subset() -> None:
    requested = {
        "assignees": [
            {"identifier_type": "open_id", "identifier": "ou_requested_b"},
            {"identifier_type": "open_id", "identifier": "ou_requested_a"},
        ]
    }
    observed = {
        "assignees": [
            {"identifier_type": "open_id", "identifier": "ou_existing"},
            {"identifier_type": "open_id", "identifier": "ou_requested_a"},
            {"identifier_type": "open_id", "identifier": "ou_requested_b"},
        ]
    }

    assert reconcile(requested, observed).verified


def test_reconcile_reports_missing_requested_assignee() -> None:
    requested = {"assignees": [{"identifier_type": "user_id", "identifier": "user_requested"}]}
    observed = {"assignees": [{"identifier_type": "user_id", "identifier": "user_other"}]}

    assert reconcile(requested, observed).mismatches == ("assignees",)
