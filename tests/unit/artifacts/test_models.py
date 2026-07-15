from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

import feishu_task_cli.artifacts.base as artifact_base
from feishu_task_cli.artifacts.canonical import canonical_bytes
from feishu_task_cli.artifacts.plan import (
    Action,
    AssigneeIdentifierType,
    AssigneeRef,
    AuthContext,
    FindingSeverity,
    PlanV1,
    TaskTarget,
)
from feishu_task_cli.artifacts.policy import PolicyV1
from feishu_task_cli.artifacts.receipt import DeclaredReviewRelationship, Outcome, ReceiptV1
from feishu_task_cli.artifacts.review import CheckedFact, ReviewV1, ReviewVerdict

NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def auth_context(account_fingerprint: str = "3" * 64) -> AuthContext:
    return AuthContext(
        api_origin="https://open.feishu.cn",
        app_id_fingerprint="1" * 64,
        tenant_fingerprint="2" * 64,
        account_fingerprint=account_fingerprint,
        acting_user_fingerprint="4" * 64,
        app_id_display="1" * 12,
        tenant_display="2" * 12,
        account_display=account_fingerprint[:12],
        acting_user_display="4" * 12,
    )


def plan(context: AuthContext) -> PlanV1:
    return PlanV1.build(
        created_at=NOW,
        tool_version="0.0.0",
        plan_id="plan_example_001",
        action=Action.CREATE,
        target=TaskTarget(tasklist_guid="tasklist_example"),
        requested_fields={"summary": "Prepare a synthetic example"},
        auth_context=context,
        expires_at=NOW + timedelta(minutes=15),
    )


def existing_task_plan(**overrides: object) -> PlanV1:
    observed_before = {"guid": "task_example", "summary": "Original synthetic example"}
    values: dict[str, object] = {
        "created_at": NOW,
        "tool_version": "0.0.0",
        "plan_id": "plan_example_002",
        "action": Action.UPDATE,
        "target": TaskTarget(task_guid="task_example"),
        "requested_fields": {"summary": "Updated synthetic example"},
        "auth_context": auth_context(),
        "expires_at": NOW + timedelta(minutes=15),
        "observed_before": observed_before,
        "precondition_fingerprint": hashlib.sha256(canonical_bytes(observed_before)).hexdigest(),
    }
    values.update(overrides)
    return PlanV1.build(**values)


def receipt(**overrides: object) -> ReceiptV1:
    created_plan = plan(auth_context())
    review = ReviewV1.build(
        created_at=NOW,
        tool_version="0.0.0",
        plan_hash=created_plan.plan_hash,
        reviewer_id="agent-reviewer",
        intended_executor_id="agent-executor",
        verdict=ReviewVerdict.APPROVED,
        expires_at=NOW + timedelta(minutes=10),
    )
    values: dict[str, object] = {
        "created_at": NOW + timedelta(seconds=2),
        "tool_version": "0.0.0",
        "action": Action.CREATE,
        "plan_hash": created_plan.plan_hash,
        "review_hash": review.review_hash,
        "declared_review_relationship": DeclaredReviewRelationship.INDEPENDENTLY_REVIEWED,
        "reviewer_id": "agent-reviewer",
        "executor_id": "agent-executor",
        "auth_context": created_plan.auth_context,
        "task_guid": "task_example",
        "requested_state": created_plan.requested_fields,
        "observed_state": created_plan.requested_fields,
        "started_at": NOW + timedelta(seconds=1),
        "completed_at": NOW + timedelta(seconds=2),
        "outcome": Outcome.VERIFIED,
    }
    values.update(overrides)
    return ReceiptV1.build(**values)


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        PlanV1.model_validate({**plan(auth_context()).model_dump(mode="json"), "surprise": True})


def test_non_utc_datetime_is_rejected() -> None:
    with pytest.raises(ValidationError, match="UTC"):
        PlanV1.build(
            created_at=datetime(2026, 1, 2, 3, 4, 5),
            tool_version="0.0.0",
            plan_id="plan_example_001",
            action=Action.CREATE,
            target=TaskTarget(tasklist_guid="tasklist_example"),
            requested_fields={},
            auth_context=auth_context(),
            expires_at=NOW + timedelta(minutes=15),
        )


def test_changed_auth_context_changes_plan_hash() -> None:
    assert plan(auth_context("3" * 64)).plan_hash != plan(auth_context("5" * 64)).plan_hash


def test_target_requires_an_explicit_identifier() -> None:
    with pytest.raises(ValidationError, match="target identifier"):
        TaskTarget()


@pytest.mark.parametrize("action", [Action.UPDATE, Action.ASSIGN, Action.COMPLETE])
def test_existing_task_actions_require_guid_and_precondition(action: Action) -> None:
    with pytest.raises(ValidationError, match="task_guid"):
        existing_task_plan(
            action=action,
            target=TaskTarget(tasklist_guid="tasklist_example"),
            observed_before=None,
            precondition_fingerprint=None,
        )


def test_create_rejects_existing_task_precondition() -> None:
    payload = plan(auth_context()).model_dump(mode="json")
    payload.update(
        observed_before={"summary": "old"},
        precondition_fingerprint="6" * 64,
    )
    payload.pop("plan_hash")
    with pytest.raises(ValidationError, match="create plan must not"):
        PlanV1.build(**payload)


@pytest.mark.parametrize(
    ("action", "requested_fields", "assignees"),
    [
        (Action.CREATE, {}, ()),
        (Action.UPDATE, {}, ()),
        (Action.UPDATE, {"owner": "unexpected"}, ()),
        (Action.COMPLETE, {"summary": "not completion"}, ()),
        (
            Action.UPDATE,
            {"summary": "Updated"},
            (AssigneeRef(identifier_type=AssigneeIdentifierType.OPEN_ID, identifier="ou_one"),),
        ),
    ],
)
def test_plan_rejects_action_specific_semantic_bypasses(
    action: Action,
    requested_fields: dict[str, object],
    assignees: tuple[AssigneeRef, ...],
) -> None:
    values = existing_task_plan().model_dump(exclude={"plan_hash"})
    values.update(action=action, requested_fields=requested_fields, assignees=assignees)
    if action is Action.CREATE:
        values.update(
            target=TaskTarget(tasklist_guid="tasklist_example"),
            observed_before=None,
            precondition_fingerprint=None,
        )

    with pytest.raises(ValidationError):
        PlanV1.build(**values)


def test_plan_rejects_more_than_50_or_noncanonical_assignees() -> None:
    values = plan(auth_context()).model_dump(exclude={"plan_hash"})
    values["assignees"] = tuple(
        AssigneeRef(
            identifier_type=AssigneeIdentifierType.OPEN_ID,
            identifier=f"ou_{index}",
        )
        for index in range(51)
    )

    with pytest.raises(ValidationError, match="50"):
        PlanV1.build(**values)

    values["assignees"] = (
        {"identifier_type": AssigneeIdentifierType.OPEN_ID, "identifier": "ou internal"},
    )
    with pytest.raises(ValidationError, match="canonical"):
        PlanV1.build(**values)


def test_assignee_ref_rejects_surrounding_identifier_whitespace() -> None:
    with pytest.raises(ValidationError, match="canonical"):
        AssigneeRef(
            identifier_type=AssigneeIdentifierType.OPEN_ID,
            identifier="  ou_example  ",
        )


def test_plan_binds_observed_before_to_precondition_fingerprint() -> None:
    with pytest.raises(ValidationError, match="observed_before"):
        existing_task_plan(precondition_fingerprint="6" * 64)


def test_supplied_hash_must_match_and_use_sha256_shape() -> None:
    payload = plan(auth_context()).model_dump(mode="json")
    payload["plan_hash"] = "not-a-sha256"

    with pytest.raises(ValidationError, match="plan_hash"):
        PlanV1.model_validate(payload)


def test_business_state_rejects_floating_point_values() -> None:
    values = plan(auth_context()).model_dump(exclude={"plan_hash"})
    values["requested_fields"] = {"progress": 0.5}

    with pytest.raises(ValidationError):
        PlanV1.build(**values)


@pytest.mark.parametrize("value", ["", "   "])
def test_authoritative_identifiers_reject_blank_values(value: str) -> None:
    plan_values = plan(auth_context()).model_dump(exclude={"plan_hash"})
    plan_values["plan_id"] = value
    with pytest.raises(ValidationError):
        PlanV1.build(**plan_values)

    with pytest.raises(ValidationError):
        ReviewV1.build(
            created_at=NOW,
            tool_version="0.0.0",
            plan_hash=plan(auth_context()).plan_hash,
            reviewer_id=value,
            verdict=ReviewVerdict.APPROVED,
            expires_at=NOW + timedelta(minutes=10),
        )

    with pytest.raises(ValidationError):
        AssigneeRef(identifier_type=AssigneeIdentifierType.OPEN_ID, identifier=value)


@pytest.mark.parametrize("replacement", [None, ""])
def test_deserialized_plan_requires_its_original_hash(replacement: str | None) -> None:
    payload = plan(auth_context()).model_dump(mode="json")
    payload["requested_fields"] = {"summary": "Tampered synthetic example"}
    if replacement is None:
        payload.pop("plan_hash")
    else:
        payload["plan_hash"] = replacement

    with pytest.raises(ValidationError, match="plan_hash"):
        PlanV1.model_validate(payload)


def test_review_policy_and_receipt_bind_their_own_hashes() -> None:
    created_plan = plan(auth_context())
    review = ReviewV1.build(
        created_at=NOW,
        tool_version="0.0.0",
        plan_hash=created_plan.plan_hash,
        reviewer_id="agent-reviewer",
        intended_executor_id="agent-executor",
        verdict=ReviewVerdict.APPROVED,
        checked_facts=(CheckedFact.ACTION, CheckedFact.AUTH_CONTEXT),
        expires_at=NOW + timedelta(minutes=10),
    )
    policy = PolicyV1.build(created_at=NOW, tool_version="0.0.0")
    receipt = ReceiptV1.build(
        created_at=NOW + timedelta(seconds=2),
        tool_version="0.0.0",
        action=Action.CREATE,
        plan_hash=created_plan.plan_hash,
        review_hash=review.review_hash,
        declared_review_relationship=DeclaredReviewRelationship.INDEPENDENTLY_REVIEWED,
        reviewer_id=review.reviewer_id,
        executor_id="agent-executor",
        auth_context=created_plan.auth_context,
        task_guid="task_example",
        requested_state=created_plan.requested_fields,
        observed_state=created_plan.requested_fields,
        started_at=NOW + timedelta(seconds=1),
        completed_at=NOW + timedelta(seconds=2),
        outcome=Outcome.VERIFIED,
    )

    hashes = (review.review_hash, policy.policy_hash, receipt.receipt_hash)
    assert all(len(value) == 64 for value in hashes)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"mismatches": ("summary",)}, "verified receipt"),
        ({"omitted_fields": ("summary",)}, "verified receipt"),
        ({"observed_state": {"summary": "different"}}, "requested state"),
        ({"task_guid": None}, "requires task_guid"),
    ],
)
def test_verified_receipt_rejects_contradictions(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        receipt(**overrides)


def test_declared_review_relationship_must_match_identities() -> None:
    with pytest.raises(ValidationError, match="relationship"):
        receipt(executor_id="agent-reviewer")


def test_partial_receipt_must_explain_why_readback_is_partial() -> None:
    with pytest.raises(ValidationError, match="partial receipt"):
        receipt(outcome=Outcome.PARTIAL)


def test_verified_receipt_accepts_requested_assignees_as_observed_subset() -> None:
    requested = {"assignees": [{"identifier_type": "open_id", "identifier": "ou_requested"}]}
    observed = {
        "assignees": [
            {"identifier_type": "open_id", "identifier": "ou_existing"},
            {"identifier_type": "open_id", "identifier": "ou_requested"},
        ]
    }

    verified = receipt(requested_state=requested, observed_state=observed)

    assert verified.outcome is Outcome.VERIFIED


def test_hash_changes_when_review_or_receipt_content_changes() -> None:
    created_plan = plan(auth_context())
    base = {
        "created_at": NOW,
        "tool_version": "0.0.0",
        "plan_hash": created_plan.plan_hash,
        "reviewer_id": "agent-reviewer",
        "verdict": ReviewVerdict.APPROVED,
        "expires_at": NOW + timedelta(minutes=10),
    }

    plain = ReviewV1.build(**base)
    warned = ReviewV1.build(**base, warnings=("synthetic warning",))
    assert plain.review_hash != warned.review_hash


def test_empty_hash_cannot_rebind_tampered_artifact() -> None:
    payload = plan(auth_context()).model_dump(mode="json")
    payload["requested_fields"] = {"summary": "tampered"}
    payload["plan_hash"] = ""

    with pytest.raises(ValidationError, match="plan_hash"):
        PlanV1.model_validate(payload)


def test_original_hash_rejects_tampered_artifact() -> None:
    payload = plan(auth_context()).model_dump(mode="json")
    payload["requested_fields"] = {"summary": "tampered"}

    with pytest.raises(ValidationError, match="does not match"):
        PlanV1.model_validate(payload)


def test_hash_generation_has_no_validation_context_backdoor() -> None:
    assert not hasattr(artifact_base, "_ARTIFACT_BUILD_TOKEN")
    payload = plan(auth_context()).model_dump(mode="json")
    payload["requested_fields"] = {"summary": "tampered"}

    with pytest.raises(ValidationError, match="does not match"):
        PlanV1.model_validate(payload, context={"artifact_build_token": object()})


def test_all_external_artifacts_reject_cleared_or_missing_integrity_hash() -> None:
    created_plan = plan(auth_context())
    review = ReviewV1.build(
        created_at=NOW,
        tool_version="0.0.0",
        plan_hash=created_plan.plan_hash,
        reviewer_id="agent-reviewer",
        verdict=ReviewVerdict.APPROVED,
        expires_at=NOW + timedelta(minutes=10),
    )
    policy = PolicyV1.build(created_at=NOW, tool_version="0.0.0")
    artifacts = (
        (created_plan, "plan_hash", "requested_fields", {"summary": "tampered"}),
        (review, "review_hash", "warnings", ["tampered"]),
        (policy, "policy_hash", "reject_warnings", True),
        (receipt(), "receipt_hash", "api_request_id", "tampered"),
    )

    for artifact, hash_field, content_field, tampered_value in artifacts:
        payload = artifact.model_dump(mode="json")
        payload[content_field] = tampered_value
        payload[hash_field] = ""
        with pytest.raises(ValidationError):
            type(artifact).model_validate(payload)

        payload.pop(hash_field)
        with pytest.raises(ValidationError):
            type(artifact).model_validate(payload)


def test_enum_values_are_stable() -> None:
    assert [item.value for item in Action] == ["create", "update", "assign", "complete"]
    assert [item.value for item in CheckedFact] == [
        "action_checked",
        "target_identity_checked",
        "assignees_checked",
        "schedule_checked",
        "auth_context_checked",
        "precondition_checked",
    ]
    assert [item.value for item in Outcome] == [
        "verified",
        "partial",
        "unknown",
        "failed",
        "rejected",
    ]
    assert [item.value for item in ReviewVerdict] == ["approved", "rejected"]
    assert [item.value for item in DeclaredReviewRelationship] == [
        "declared_self_reviewed",
        "declared_independently_reviewed",
    ]
    assert [item.value for item in AssigneeIdentifierType] == [
        "open_id",
        "user_id",
        "union_id",
    ]
    assert [item.value for item in FindingSeverity] == ["info", "warning", "error"]
