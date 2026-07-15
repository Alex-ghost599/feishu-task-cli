import pytest

from scripts.privacy_scan import scan_text


def test_detects_real_personal_home_path() -> None:
    findings = scan_text("path=/" + "Users/alice/private/file.txt", "fixture")
    assert findings == ["fixture: personal_home_path"]


def test_detects_example_subdirectory_under_real_home() -> None:
    findings = scan_text("path=/" + "Users/alice/example/private.txt", "fixture")
    assert findings == ["fixture: personal_home_path"]


def test_allows_synthetic_feishu_identifier() -> None:
    assert scan_text("open_id=ou_test_example", "fixture") == []


def test_detects_authorization_value() -> None:
    value = "Author" + "ization: Bearer " + "secret-value"
    findings = scan_text(value, "fixture")
    assert findings == ["fixture: authorization_value"]


@pytest.mark.parametrize(
    ("value", "label"),
    [
        ('{"Author' + 'ization": "Bearer ' + "a" * 24 + '"}', "authorization_value"),
        ("{'Author" + "ization': 'Bearer " + "b" * 24 + "'}", "authorization_value"),
        ("app_id=" + "cli_" + "a" * 24, "real_app_id"),
        ("user_id=" + "u_" + "a" * 24, "real_user_id"),
        (
            "task_guid=" + "12345678-1234-4abc-8def-1234567890ab",
            "real_task_guid",
        ),
        (
            "tasklist_guid=" + "87654321-4321-4abc-8def-ba0987654321",
            "real_tasklist_guid",
        ),
        ("tenant_key=" + "tenant_" + "a" * 24, "real_tenant_key"),
    ],
)
def test_detects_public_boundary_values(value: str, label: str) -> None:
    assert scan_text(value, "fixture") == [f"fixture: {label}"]


@pytest.mark.parametrize(
    "value",
    [
        "app_id=cli_test_example",
        "user_id=test-user",
        "task_guid=00000000-0000-0000-0000-000000000000",
        "tasklist_guid=00000000-0000-0000-0000-000000000000",
        "tenant_key=tenant_test_example",
    ],
)
def test_allows_explicit_synthetic_values(value: str) -> None:
    assert scan_text(value, "fixture") == []
