from __future__ import annotations

import errno
import json
import os
import stat
import sys
import uuid
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Protocol, cast

import typer
import yaml
from pydantic import BaseModel, ValidationError
from typer import _click as click
from typer.core import TyperGroup

from feishu_task_cli.application.executor import Executor, exit_code_for_receipt
from feishu_task_cli.application.planner import Planner
from feishu_task_cli.application.policy_engine import build_neutral_policy
from feishu_task_cli.application.reviewer import build_review
from feishu_task_cli.artifacts.base import JsonValueNoFloat
from feishu_task_cli.artifacts.plan import PlanV1
from feishu_task_cli.artifacts.policy import PolicyV1
from feishu_task_cli.artifacts.receipt import ReceiptV1
from feishu_task_cli.artifacts.review import CheckedFact, ReviewV1, ReviewVerdict
from feishu_task_cli.auth.config import ConfigError, Settings, UnsafeConfigError
from feishu_task_cli.auth.context import resolve_auth_context
from feishu_task_cli.auth.keyring_store import TokenStore, TokenStoreError
from feishu_task_cli.auth.oauth import AuthStatus, OAuthClient, OAuthError
from feishu_task_cli.errors import (
    ArtifactIntegrityError,
    AuthContextMismatchError,
    ExecutionInProgressError,
    FeishuResponseError,
    FeishuTaskError,
    JournalCorruptError,
    JournalPermissionError,
    PolicyRejectedError,
    PreconditionChangedError,
    ReplayBlockedError,
    UnknownExecutionError,
)
from feishu_task_cli.feishu.client import FeishuAPIError, FeishuClient, FeishuTransportError
from feishu_task_cli.feishu.tasks import TaskGateway
from feishu_task_cli.journal.store import ExecutionJournal
from feishu_task_cli.presentation.markdown import render_markdown
from feishu_task_cli.presentation.next_actions import (
    NEXT_ACTION_MAPPING_VERSION,
    ErrorCode,
    next_action_for_error,
)


class OutputCleanupStatus(StrEnum):
    """Fixed, non-sensitive status for an output residue that could not be removed."""

    INCOMPLETE_WIPED = "incomplete_wiped"
    INCOMPLETE_UNVERIFIED = "incomplete_unverified"


def _safe_error_envelope(
    code: ErrorCode,
    category: str,
    message: str,
    *,
    retryable: bool = False,
    output_cleanup_status: OutputCleanupStatus | None = None,
) -> dict[str, object]:
    error: dict[str, object] = {
        "category": category,
        "code": code.value,
        "message": message,
        "next_action": next_action_for_error(code).value,
        "next_action_mapping_version": NEXT_ACTION_MAPPING_VERSION,
        "retryable": retryable,
    }
    if output_cleanup_status is not None:
        error["output_cleanup_status"] = output_cleanup_status.value
    return {"error": error}


class AgentTyperGroup(TyperGroup):
    """Convert Click/Typer usage failures to the stable Agent JSON contract."""

    def main(
        self,
        args: Sequence[str] | None = None,
        prog_name: str | None = None,
        complete_var: str | None = None,
        standalone_mode: bool = True,
        windows_expand_args: bool = True,
        **extra: Any,
    ) -> Any:
        del standalone_mode
        try:
            result = super().main(
                args=args,
                prog_name=prog_name,
                complete_var=complete_var,
                standalone_mode=False,
                windows_expand_args=windows_expand_args,
                **extra,
            )
        except click.ClickException:
            envelope = _safe_error_envelope(
                ErrorCode.INVALID_INPUT,
                "input",
                "Input could not be safely validated.",
            )
            sys.stdout.write(json.dumps(envelope, ensure_ascii=False, sort_keys=True) + "\n")
            click.echo("error: invalid_input", err=True)
            raise SystemExit(2) from None
        if isinstance(result, int) and result != 0:
            raise SystemExit(result)
        return result


app = typer.Typer(
    cls=AgentTyperGroup,
    help="Agent-native Feishu Task CLI with review-gated writes.",
)
auth_app = typer.Typer(help="Explicit OAuth setup and status.")
task_app = typer.Typer(help="Read Feishu Tasks.")
plan_app = typer.Typer(help="Build immutable mutation Plans.")
execution_app = typer.Typer(help="Inspect local execution state.")
schema_app = typer.Typer(help="Inspect versioned agent artifact schemas.")
app.add_typer(auth_app, name="auth")
app.add_typer(task_app, name="task")
app.add_typer(plan_app, name="plan")
app.add_typer(execution_app, name="execution")
app.add_typer(schema_app, name="schema")


class OAuthRuntime(Protocol):
    def login(self, *, scopes: tuple[str, ...], open_browser: bool = True) -> None: ...

    def status(self) -> AuthStatus: ...

    def logout(self) -> None: ...


class RuntimeProtocol(Protocol):
    @property
    def oauth(self) -> OAuthRuntime: ...

    @property
    def gateway(self) -> TaskGateway: ...

    @property
    def planner(self) -> Planner: ...

    @property
    def journal(self) -> ExecutionJournal: ...

    @property
    def executor(self) -> Executor: ...


@dataclass
class Runtime:
    """Lazy production dependency assembly; construction does not contact Feishu."""

    settings: Settings
    oauth: OAuthClient
    journal_path: Path | None = None
    _gateway: TaskGateway | None = None
    _journal: ExecutionJournal | None = None
    _planner: Planner | None = None
    _executor: Executor | None = None

    def _access_token(self) -> str:
        token = self.oauth.access_token()
        if token is None:
            self.oauth.refresh()
            token = self.oauth.access_token()
        if token is None:
            raise OAuthError("authentication refresh did not provide an access token")
        return token

    @property
    def gateway(self) -> TaskGateway:
        if self._gateway is None:
            client = FeishuClient(
                api_origin=self.settings.api_origin,
                access_token=self._access_token(),
            )
            self._gateway = TaskGateway(client)
        return self._gateway

    @property
    def journal(self) -> ExecutionJournal:
        if self._journal is None:
            self._journal = ExecutionJournal(self.journal_path)
        return self._journal

    @property
    def planner(self) -> Planner:
        if self._planner is None:
            self._planner = Planner(self.gateway, resolve_auth_context(self.oauth))
        return self._planner

    @property
    def executor(self) -> Executor:
        if self._executor is None:
            self._executor = Executor(
                self.gateway,
                auth_context_resolver=lambda: resolve_auth_context(self.oauth),
                journal=self.journal,
            )
        return self._executor


def runtime_factory(
    *, config_path: str | None = None, journal_path: str | None = None
) -> RuntimeProtocol:
    settings = Settings.load(config_path)
    if settings.app_id is None or settings.account_id is None:
        raise ConfigError("FEISHU_APP_ID and FEISHU_ACCOUNT_ID are required")
    store = TokenStore(app_id=settings.app_id, account_id=settings.account_id)
    return Runtime(
        settings=settings,
        oauth=OAuthClient(
            settings=settings,
            store=store,
            authorization_url_output=lambda url: typer.echo(
                f"Open this explicit OAuth authorization URL: {url}", err=True
            ),
        ),
        journal_path=Path(journal_path) if journal_path is not None else None,
    )


def _read_text(source: str) -> str:
    return sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")


def _read_json(source: str) -> object:
    return json.loads(_read_text(source))


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode()


def _open_output_parent(path: Path) -> int:
    """Open every parent component without following symlinks."""
    parent = path.parent
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(parent.anchor, flags)
    owned = {descriptor}
    try:
        for component in parent.parts[1:]:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            owned.add(next_descriptor)
            descriptor = next_descriptor
        details = os.fstat(descriptor)
        if not stat.S_ISDIR(details.st_mode):
            raise ValueError("output parent must be a real directory")
        if hasattr(os, "getuid") and details.st_uid != os.getuid():
            raise ValueError("output parent must be owned by the current user")
        if stat.S_IMODE(details.st_mode) & 0o022:
            raise ValueError("output parent must not be writable by other users")
        for ancestor in tuple(owned):
            if ancestor != descriptor:
                _close_owned(owned, ancestor)
        owned.remove(descriptor)
        return descriptor
    except BaseException:
        _best_effort_close_all(owned)
        raise


def _close_owned(owned: set[int], descriptor: int) -> None:
    """Transfer one descriptor out of cleanup ownership before its one close attempt."""
    owned.remove(descriptor)
    os.close(descriptor)


def _best_effort_close_all(owned: set[int]) -> None:
    for descriptor in tuple(owned):
        _best_effort_close_owned(owned, descriptor)


def _best_effort_close_owned(owned: set[int], descriptor: int) -> None:
    if descriptor not in owned:
        return
    owned.remove(descriptor)
    with suppress(OSError):
        os.close(descriptor)


def _write_all(descriptor: int, content: bytes) -> None:
    remaining = memoryview(content)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("atomic output write made no progress")
        remaining = remaining[written:]


def _unlink_temporary(temporary_name: str, parent_fd: int) -> bool:
    """Bound retryable unlink work and confirm whether the name still exists."""
    for attempt in range(2):
        try:
            os.unlink(temporary_name, dir_fd=parent_fd)
            return True
        except FileNotFoundError:
            return True
        except OSError as error:
            if error.errno == errno.EINTR and attempt == 0:
                continue
            break
    try:
        os.stat(temporary_name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return True
    except OSError:
        pass
    return False


def _wipe_verified_temporary(
    temporary_name: str,
    parent_fd: int,
    expected: os.stat_result | None,
) -> bool:
    """Wipe only the exact private regular file created by this process."""
    if expected is None:
        return False
    flags = os.O_WRONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(temporary_name, flags, dir_fd=parent_fd)
    except OSError:
        return False
    owned = {descriptor}
    try:
        actual = os.fstat(descriptor)
        if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
            return False
        if not stat.S_ISREG(actual.st_mode):
            return False
        if hasattr(os, "getuid") and actual.st_uid != os.getuid():
            return False
        if stat.S_IMODE(actual.st_mode) != 0o600:
            return False
        os.ftruncate(descriptor, 0)
        os.fsync(descriptor)
        return True
    except OSError:
        return False
    finally:
        _best_effort_close_all(owned)


def _cleanup_temporary(
    temporary_name: str,
    parent_fd: int,
    expected: os.stat_result | None,
) -> OutputCleanupStatus | None:
    if _unlink_temporary(temporary_name, parent_fd):
        return None
    wiped = _wipe_verified_temporary(temporary_name, parent_fd, expected)
    if _unlink_temporary(temporary_name, parent_fd):
        return None
    if wiped:
        return OutputCleanupStatus.INCOMPLETE_WIPED
    return OutputCleanupStatus.INCOMPLETE_UNVERIFIED


def _write_atomic(path: Path, content: bytes) -> None:
    path = path.expanduser().absolute()
    parent_fd = _open_output_parent(path)
    temporary_name = f".{path.name}.{uuid.uuid4().hex}.tmp"
    owned = {parent_fd}
    temporary_fd: int | None = None
    temporary_details: os.stat_result | None = None
    primary: BaseException | None = None
    primary_traceback = None
    try:
        try:
            existing = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if stat.S_ISLNK(existing.st_mode) or not stat.S_ISREG(existing.st_mode):
                raise ValueError("output target must be a regular file, never a symlink")
            if hasattr(os, "getuid") and existing.st_uid != os.getuid():
                raise ValueError("output target must be owned by the current user")
        temporary_fd = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=parent_fd,
        )
        owned.add(temporary_fd)
        temporary_details = os.fstat(temporary_fd)
        _write_all(temporary_fd, content)
        os.fsync(temporary_fd)
        _close_owned(owned, temporary_fd)
        os.replace(
            temporary_name,
            path.name,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        os.chmod(path.name, 0o600, dir_fd=parent_fd, follow_symlinks=False)
        os.fsync(parent_fd)
    except BaseException as error:
        primary = error
        primary_traceback = error.__traceback__

    if temporary_fd is not None:
        _best_effort_close_owned(owned, temporary_fd)
    cleanup_status = _cleanup_temporary(temporary_name, parent_fd, temporary_details)
    _best_effort_close_owned(owned, parent_fd)
    _best_effort_close_all(owned)

    if primary is not None:
        if cleanup_status is not None:
            primary.output_cleanup_status = cleanup_status  # type: ignore[attr-defined]
        raise primary.with_traceback(primary_traceback)


def _artifact_envelope(artifact: BaseModel, path: Path) -> dict[str, object]:
    payload = artifact.model_dump(mode="json")
    artifact_type = payload.get("artifact_type")
    if not isinstance(artifact_type, str):
        raise ValueError("artifact type is missing")
    hash_value = payload.get(f"{artifact_type}_hash")
    if not isinstance(hash_value, str):
        raise ValueError("artifact hash is missing")
    return {"artifact_hash": hash_value, "artifact_type": artifact_type, "path": str(path)}


def _emit_artifact(artifact: BaseModel, output: str, diagnostic: str) -> None:
    content = _json_bytes(artifact.model_dump(mode="json"))
    if output == "-":
        sys.stdout.buffer.write(content)
    else:
        destination = Path(output)
        _write_atomic(destination, content)
        sys.stdout.buffer.write(_json_bytes(_artifact_envelope(artifact, destination)))
    typer.echo(diagnostic, err=True)


def _emit_value(value: object, output: str, *, artifact_type: str) -> None:
    content = _json_bytes(value)
    if output == "-":
        sys.stdout.buffer.write(content)
        return
    destination = Path(output)
    _write_atomic(destination, content)
    envelope = {"artifact_type": artifact_type, "path": str(destination)}
    sys.stdout.buffer.write(_json_bytes(envelope))


def _is_integrity_validation(error: ValidationError) -> bool:
    return any(
        isinstance(item.get("ctx", {}).get("error"), ArtifactIntegrityError)
        for item in error.errors(include_url=False)
    )


def _fail(
    code: ErrorCode,
    category: str,
    message: str,
    exit_code: int,
    *,
    retryable: bool = False,
    output_cleanup_status: OutputCleanupStatus | None = None,
) -> None:
    envelope = _safe_error_envelope(
        code,
        category,
        message,
        retryable=retryable,
        output_cleanup_status=output_cleanup_status,
    )
    sys.stdout.buffer.write(_json_bytes(envelope))
    typer.echo(f"error: {code.value}", err=True)
    raise typer.Exit(exit_code)


def _handle(error: Exception) -> None:
    if isinstance(error, ArtifactIntegrityError) or (
        isinstance(error, ValidationError) and _is_integrity_validation(error)
    ):
        _fail(
            ErrorCode.ARTIFACT_INTEGRITY_FAILED,
            "integrity",
            "Artifact integrity validation failed.",
            8,
        )
    if isinstance(error, (ConfigError, UnsafeConfigError, OAuthError, TokenStoreError)):
        _fail(
            ErrorCode.AUTHENTICATION_FAILED,
            "authentication",
            "Authentication is not configured.",
            3,
        )
    if isinstance(error, PolicyRejectedError):
        _fail(
            ErrorCode.POLICY_REJECTED,
            "policy",
            "Execution was rejected by review or policy.",
            4,
        )
    if isinstance(error, ExecutionInProgressError):
        _fail(
            ErrorCode.EXECUTION_IN_PROGRESS,
            "execution",
            "A local executor is active.",
            6,
            retryable=True,
        )
    if isinstance(error, UnknownExecutionError):
        _fail(
            ErrorCode.EXECUTION_UNKNOWN,
            "execution",
            "Execution outcome is unknown; do not replay.",
            6,
        )
    if isinstance(error, ReplayBlockedError):
        _fail(ErrorCode.REPLAY_BLOCKED, "execution", "This Plan cannot be replayed.", 4)
    if isinstance(error, (AuthContextMismatchError, PreconditionChangedError)):
        _fail(
            ErrorCode.POLICY_REJECTED,
            "policy",
            "Execution preconditions were not satisfied.",
            4,
        )
    if isinstance(error, (FeishuAPIError, FeishuTransportError, FeishuResponseError)):
        _fail(ErrorCode.API_FAILED, "remote", "Feishu request failed safely.", 5)
    if isinstance(error, (JournalCorruptError, JournalPermissionError)):
        _fail(
            ErrorCode.CONFIGURATION_FAILED,
            "configuration",
            "Local execution state is unsafe.",
            3,
        )
    if isinstance(
        error,
        (
            ValidationError,
            ValueError,
            TypeError,
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            yaml.YAMLError,
        ),
    ):
        cleanup_status = getattr(error, "output_cleanup_status", None)
        if not isinstance(cleanup_status, OutputCleanupStatus):
            cleanup_status = None
        _fail(
            ErrorCode.INVALID_INPUT,
            "input",
            "Input could not be safely validated.",
            2,
            output_cleanup_status=cleanup_status,
        )
    if isinstance(error, FeishuTaskError):
        _fail(ErrorCode.OPERATION_FAILED, "operation", "Operation failed safely.", 5)
    _fail(ErrorCode.OPERATION_FAILED, "operation", "Operation failed safely.", 5)


def _runtime(config: str | None, journal_dir: str | None = None) -> RuntimeProtocol:
    return runtime_factory(config_path=config, journal_path=journal_dir)


def _mapping_input(source: str | None) -> dict[str, JsonValueNoFloat]:
    if source is None:
        return {}
    value = _read_json(source)
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ValueError("input must be a JSON object")
    return cast(dict[str, JsonValueNoFloat], dict(value))


@auth_app.command("login")
def auth_login(
    config: Annotated[str | None, typer.Option("--config")] = None,
    open_browser: Annotated[bool, typer.Option("--browser/--no-browser")] = True,
) -> None:
    """Run the one explicit human OAuth setup command."""
    try:
        runtime = _runtime(config)
        runtime.oauth.login(
            scopes=("task:task:read", "task:task:write"),
            open_browser=open_browser,
        )
        status = runtime.oauth.status()
        _emit_value(
            {
                "authenticated": status.authenticated,
                "auth_context": (
                    status.auth_context.model_dump(mode="json") if status.auth_context else None
                ),
            },
            "-",
            artifact_type="auth_status",
        )
    except Exception as error:
        _handle(error)


@auth_app.command("status")
def auth_status(config: Annotated[str | None, typer.Option("--config")] = None) -> None:
    try:
        status = _runtime(config).oauth.status()
        payload: dict[str, object] = {"authenticated": status.authenticated}
        if status.auth_context is not None:
            payload["auth_context"] = status.auth_context.model_dump(mode="json")
        _emit_value(payload, "-", artifact_type="auth_status")
    except Exception as error:
        _handle(error)


@auth_app.command("logout")
def auth_logout(config: Annotated[str | None, typer.Option("--config")] = None) -> None:
    try:
        _runtime(config).oauth.logout()
        _emit_value({"authenticated": False}, "-", artifact_type="auth_status")
    except Exception as error:
        _handle(error)


@task_app.command("get")
def task_get(
    task_guid: Annotated[str, typer.Option("--task-guid")],
    output: Annotated[str, typer.Option("--output")] = "-",
    config: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    try:
        task = _runtime(config).gateway.get(task_guid)
        _emit_value({"task": task.to_state()}, output, artifact_type="task_snapshot")
    except Exception as error:
        _handle(error)


@plan_app.command("create")
def plan_create(
    tasklist_guid: Annotated[str, typer.Option("--tasklist-guid")],
    input_source: Annotated[str | None, typer.Option("--input")] = None,
    summary: Annotated[str | None, typer.Option("--summary")] = None,
    description: Annotated[str | None, typer.Option("--description")] = None,
    assignees: Annotated[list[str] | None, typer.Option("--assignee")] = None,
    output: Annotated[str, typer.Option("--output")] = "-",
    config: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    try:
        fields = _mapping_input(input_source)
        if summary is not None:
            fields["summary"] = summary
        if description is not None:
            fields["description"] = description
        plan = _runtime(config).planner.create(
            requested_fields=fields,
            tasklist_guid=tasklist_guid,
            assignees=assignees or (),
        )
        _emit_artifact(plan, output, "created plan artifact")
    except Exception as error:
        _handle(error)


@plan_app.command("update")
def plan_update(
    task_guid: Annotated[str, typer.Option("--task-guid")],
    input_source: Annotated[str | None, typer.Option("--input")] = None,
    summary: Annotated[str | None, typer.Option("--summary")] = None,
    description: Annotated[str | None, typer.Option("--description")] = None,
    output: Annotated[str, typer.Option("--output")] = "-",
    config: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    try:
        fields = _mapping_input(input_source)
        if summary is not None:
            fields["summary"] = summary
        if description is not None:
            fields["description"] = description
        plan = _runtime(config).planner.update(task_guid, fields)
        _emit_artifact(plan, output, "created plan artifact")
    except Exception as error:
        _handle(error)


@plan_app.command("assign")
def plan_assign(
    task_guid: Annotated[str, typer.Option("--task-guid")],
    assignees: Annotated[list[str], typer.Option("--assignee")],
    output: Annotated[str, typer.Option("--output")] = "-",
    config: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    try:
        plan = _runtime(config).planner.assign(task_guid, assignees)
        _emit_artifact(plan, output, "created plan artifact")
    except Exception as error:
        _handle(error)


@plan_app.command("complete")
def plan_complete(
    task_guid: Annotated[str, typer.Option("--task-guid")],
    output: Annotated[str, typer.Option("--output")] = "-",
    config: Annotated[str | None, typer.Option("--config")] = None,
) -> None:
    try:
        plan = _runtime(config).planner.complete(task_guid)
        _emit_artifact(plan, output, "created plan artifact")
    except Exception as error:
        _handle(error)


@app.command("review")
def review_command(
    plan_path: Annotated[str, typer.Option("--plan", help="Plan JSON path, or - for stdin.")],
    reviewer_id: Annotated[str, typer.Option("--reviewer-id")],
    verdict: Annotated[ReviewVerdict, typer.Option("--verdict")],
    intended_executor_id: Annotated[str | None, typer.Option("--intended-executor-id")] = None,
    checked_facts: Annotated[list[CheckedFact] | None, typer.Option("--checked-fact")] = None,
    warnings: Annotated[list[str] | None, typer.Option("--warning")] = None,
    reasons: Annotated[list[str] | None, typer.Option("--reason")] = None,
    ttl_seconds: Annotated[int, typer.Option("--ttl-seconds", min=1)] = 900,
    output: Annotated[str, typer.Option("--output")] = "-",
) -> None:
    try:
        plan = PlanV1.model_validate_json(_read_text(plan_path))
        review = build_review(
            plan,
            reviewer_id,
            verdict,
            intended_executor_id=intended_executor_id,
            checked_facts=checked_facts or (),
            warnings=warnings or (),
            reasons=reasons or (),
            ttl_seconds=ttl_seconds,
        )
        _emit_artifact(review, output, "created review artifact")
    except Exception as error:
        _handle(error)


def _policy(source: str | None) -> PolicyV1:
    if source is None:
        return build_neutral_policy()
    text = _read_text(source)
    if Path(source).suffix.lower() in {".yaml", ".yml"}:
        return PolicyV1.model_validate(yaml.safe_load(text))
    return PolicyV1.model_validate_json(text)


@app.command("execute")
def execute_command(
    plan_path: Annotated[str, typer.Option("--plan")],
    review_path: Annotated[str, typer.Option("--review")],
    executor_id: Annotated[str, typer.Option("--executor-id")],
    policy_path: Annotated[str | None, typer.Option("--policy")] = None,
    output: Annotated[str, typer.Option("--output")] = "-",
    config: Annotated[str | None, typer.Option("--config")] = None,
    journal_dir: Annotated[str | None, typer.Option("--journal-dir")] = None,
) -> None:
    try:
        plan = PlanV1.model_validate_json(_read_text(plan_path))
        review = ReviewV1.model_validate_json(_read_text(review_path))
        policy = _policy(policy_path)
        runtime = _runtime(config, journal_dir)
        receipt = runtime.executor.execute(
            plan,
            review,
            policy,
            executor_id,
        )
        _emit_artifact(receipt, output, "created execution receipt")
        code = exit_code_for_receipt(receipt)
        if code:
            raise typer.Exit(code)
    except typer.Exit:
        raise
    except Exception as error:
        _handle(error)


@execution_app.command("status")
def execution_status(
    plan_hash: Annotated[str, typer.Option("--plan-hash")],
    journal_dir: Annotated[str | None, typer.Option("--journal-dir")] = None,
) -> None:
    try:
        journal = ExecutionJournal(Path(journal_dir) if journal_dir is not None else None)
        record = journal.status(plan_hash)
        payload: dict[str, object] = {"plan_hash": plan_hash, "state": "not_started"}
        if record is not None:
            payload = {
                "plan_hash": plan_hash,
                "state": record.state.value,
                "started_at": record.started_at.isoformat().replace("+00:00", "Z"),
                "updated_at": record.updated_at.isoformat().replace("+00:00", "Z"),
            }
        _emit_value(payload, "-", artifact_type="execution_status")
    except Exception as error:
        _handle(error)


@app.command("render")
def render_command(
    artifact_path: Annotated[str, typer.Option("--artifact")],
    format_name: Annotated[str, typer.Option("--format")] = "markdown",
    output: Annotated[str, typer.Option("--output")] = "-",
) -> None:
    try:
        if format_name != "markdown":
            raise ValueError("format must be markdown")
        payload = _read_json(artifact_path)
        if not isinstance(payload, Mapping):
            raise ValueError("artifact must be a JSON object")
        rendered = render_markdown(cast(Mapping[str, object], payload))
        if output == "-":
            sys.stdout.write(rendered)
        else:
            destination = Path(output)
            _write_atomic(destination, rendered.encode())
            sys.stdout.buffer.write(
                _json_bytes(
                    {"artifact_type": "markdown", "format": "markdown", "path": str(destination)}
                )
            )
    except Exception as error:
        _handle(error)


@schema_app.command("show")
def schema_show(
    artifact: Annotated[str, typer.Option("--artifact")],
    output: Annotated[str, typer.Option("--output")] = "-",
) -> None:
    try:
        models: dict[str, type[BaseModel]] = {
            "plan": PlanV1,
            "review": ReviewV1,
            "policy": PolicyV1,
            "receipt": ReceiptV1,
        }
        model = models.get(artifact)
        if model is None:
            raise ValueError("artifact must be plan, review, policy, or receipt")
        _emit_value(model.model_json_schema(), output, artifact_type="json_schema")
    except Exception as error:
        _handle(error)
