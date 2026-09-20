import contextlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app.config import REPO_ROOT, Settings
from app.main import create_app
from app.security import filesystem
from app.security.filesystem import (
    ANY_RIGHTS,
    DELETE,
    FILE_APPEND_DATA,
    FILE_DELETE_CHILD,
    FILE_READ_DATA,
    FILE_WRITE_DATA,
    GENERIC_ALL,
    GENERIC_WRITE,
    INHERIT_ONLY,
    MAXIMUM_ALLOWED,
    OBJECT_INHERIT,
    SID_ADMINISTRATORS,
    SID_AUTHENTICATED_USERS,
    SID_CREATOR_OWNER,
    SID_EVERYONE,
    SID_OWNER_RIGHTS,
    SID_SYSTEM,
    SID_USERS,
    SYNCHRONIZE,
    WRITE_DAC,
    WRITE_OWNER,
    WRITE_RIGHTS,
    AclEntry,
    AclReport,
    Level,
    UnsafePermissionsError,
    check_path,
    current_user_sid,
    ensure_private_directory,
    evaluate,
    read_acl,
    verify_or_raise,
)

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows ACLs")

ME = "S-1-5-21-1111-2222-3333-1001"
OTHER = "S-1-5-21-1111-2222-3333-1099"
TRUSTED = frozenset({ME})
READ_EXECUTE = FILE_READ_DATA | 0x20 | 0x80 | 0x20000
FULL = 0x1F01FF


def report(*entries: AclEntry, owner: str | None = ME, null_dacl: bool = False) -> AclReport:
    return AclReport("C:\\x", owner, list(entries), null_dacl)


def allow(sid: str, mask: int, flags: int = 0) -> AclEntry:
    return AclEntry(sid, mask, flags, True)


def deny(sid: str, mask: int) -> AclEntry:
    return AclEntry(sid, mask, 0, False)


OWNERS_ONLY = report(allow(ME, FULL), allow(SID_SYSTEM, FULL), allow(SID_ADMINISTRATORS, FULL))


# ---------- pure policy ----------


@pytest.mark.parametrize("level", list(Level))
def test_owner_system_and_administrators_are_allowed(level):
    assert evaluate(OWNERS_ONLY, level, TRUSTED) == []


@pytest.mark.parametrize("principal", [SID_USERS, SID_EVERYONE, SID_AUTHENTICATED_USERS, OTHER])
@pytest.mark.parametrize(
    "mask",
    [
        FILE_WRITE_DATA,
        FILE_APPEND_DATA,
        FILE_DELETE_CHILD,
        DELETE,
        WRITE_DAC,
        WRITE_OWNER,
        GENERIC_WRITE,
        GENERIC_ALL,
        MAXIMUM_ALLOWED,
        FULL,
    ],
)
def test_write_rights_for_any_other_principal_are_rejected(principal, mask):
    problems = evaluate(report(allow(ME, FULL), allow(principal, mask)), Level.NO_FOREIGN_WRITE, TRUSTED)

    assert [p.kind for p in problems] == ["foreign_write"]
    assert problems[0].principal == principal


@pytest.mark.parametrize("principal", [SID_USERS, SID_EVERYONE, SID_AUTHENTICATED_USERS, OTHER])
def test_read_only_access_is_allowed_for_code_but_rejected_for_private_paths(principal):
    acl = report(allow(ME, FULL), allow(principal, READ_EXECUTE))

    assert evaluate(acl, Level.NO_FOREIGN_WRITE, TRUSTED) == []
    problems = evaluate(acl, Level.PRIVATE, TRUSTED)
    assert [p.kind for p in problems] == ["foreign_access"]


def test_synchronize_alone_is_not_access():
    assert evaluate(report(allow(ME, FULL), allow(OTHER, SYNCHRONIZE)), Level.PRIVATE, TRUSTED) == []


def test_a_deny_entry_never_excuses_an_allow_entry():
    acl = report(allow(ME, FULL), deny(SID_USERS, FILE_WRITE_DATA), allow(SID_USERS, FILE_WRITE_DATA))

    assert [p.kind for p in evaluate(acl, Level.NO_FOREIGN_WRITE, TRUSTED)] == ["foreign_write"]


def test_inherit_only_entries_that_will_reach_children_count():
    acl = report(allow(ME, FULL), allow(SID_USERS, FULL, INHERIT_ONLY | OBJECT_INHERIT))

    assert evaluate(acl, Level.NO_FOREIGN_WRITE, TRUSTED) != []


def test_inherit_only_entries_that_reach_nothing_are_ignored():
    acl = report(allow(ME, FULL), allow(SID_USERS, FULL, INHERIT_ONLY))

    assert evaluate(acl, Level.NO_FOREIGN_WRITE, TRUSTED) == []


def test_creator_owner_and_owner_rights_placeholders_are_allowed():
    acl = report(allow(ME, FULL), allow(SID_CREATOR_OWNER, FULL), allow(SID_OWNER_RIGHTS, FULL))

    assert evaluate(acl, Level.PRIVATE, TRUSTED) == []


@pytest.mark.parametrize("owner", [ME, SID_ADMINISTRATORS, SID_SYSTEM])
def test_expected_owners_are_accepted(owner):
    assert evaluate(report(allow(ME, FULL), owner=owner), Level.PRIVATE, TRUSTED) == []


def test_a_foreign_owner_is_rejected_because_owners_can_rewrite_permissions():
    problems = evaluate(report(allow(ME, FULL), owner=OTHER), Level.NO_FOREIGN_WRITE, TRUSTED)

    assert [(p.kind, p.principal) for p in problems] == [("foreign_owner", OTHER)]


def test_a_missing_dacl_means_everyone_has_full_control():
    problems = evaluate(report(null_dacl=True), Level.NO_FOREIGN_WRITE, TRUSTED)

    assert [p.kind for p in problems] == ["null_dacl"]


def test_parents_that_let_others_delete_or_rewrite_the_folder_are_rejected():
    for mask in (FILE_DELETE_CHILD, DELETE, WRITE_DAC, WRITE_OWNER, GENERIC_ALL):
        problems = evaluate(
            report(allow(ME, FULL), allow(SID_USERS, mask)), Level.NO_FOREIGN_WRITE, TRUSTED, ancestor=True
        )
        assert [p.kind for p in problems] == ["replaceable_parent"], hex(mask)


def test_parents_that_only_allow_creating_files_are_fine():
    acl = report(allow(ME, FULL), allow(SID_AUTHENTICATED_USERS, FILE_WRITE_DATA | FILE_APPEND_DATA))

    assert evaluate(acl, Level.NO_FOREIGN_WRITE, TRUSTED, ancestor=True) == []


def test_parent_entries_that_only_apply_to_descendants_are_ignored():
    acl = report(allow(ME, FULL), allow(SID_USERS, FULL, INHERIT_ONLY | OBJECT_INHERIT))

    assert evaluate(acl, Level.NO_FOREIGN_WRITE, TRUSTED, ancestor=True) == []


def test_write_rights_mask_covers_every_way_to_modify():
    for right in (FILE_WRITE_DATA, FILE_APPEND_DATA, DELETE, WRITE_DAC, WRITE_OWNER, GENERIC_ALL):
        assert WRITE_RIGHTS & right
    assert not WRITE_RIGHTS & FILE_READ_DATA
    assert ANY_RIGHTS & FILE_READ_DATA and not ANY_RIGHTS & SYNCHRONIZE


# ---------- real Windows ACLs ----------


def icacls_text(path: Path) -> str:
    return subprocess.run(["icacls", str(path)], capture_output=True, text=True, check=False).stdout


def grant(path: Path, sid: str, rights: str = "M") -> None:
    completed = subprocess.run(
        ["icacls", str(path), "/grant", f"*{sid}:(OI)(CI){rights}"], capture_output=True, check=False
    )
    assert completed.returncode == 0, completed.stderr


@pytest.fixture
def unsafe_directory(tmp_path) -> Path:
    directory = tmp_path / "shared"
    directory.mkdir()
    grant(directory, SID_USERS)
    return directory


@windows_only
def test_current_user_sid_looks_like_a_windows_account_sid():
    assert current_user_sid().startswith("S-1-5-21-")


@windows_only
def test_owner_of_a_new_directory_is_the_current_user_or_administrators(tmp_path):
    owner = read_acl(tmp_path).owner

    assert owner in {current_user_sid(), SID_ADMINISTRATORS, SID_SYSTEM}


@windows_only
@pytest.mark.parametrize("sid", [SID_USERS, SID_EVERYONE, SID_AUTHENTICATED_USERS])
def test_real_grants_to_broad_groups_are_detected(tmp_path, sid):
    directory = tmp_path / "d"
    directory.mkdir()
    grant(directory, sid)

    problems = check_path(directory, Level.NO_FOREIGN_WRITE)

    assert sid in {p.principal for p in problems if p.kind == "foreign_write"}


def assert_only_allowed_principals(directory: Path) -> None:
    """Required principals present, nothing outside the allowed set. Windows may add the
    OWNER RIGHTS placeholder on some machines (seen on GitHub runners), which grants nothing."""
    required = {current_user_sid(), SID_SYSTEM, SID_ADMINISTRATORS}
    present = {entry.sid for entry in read_acl(directory).entries}
    assert required <= present <= required | {SID_OWNER_RIGHTS}


@windows_only
def test_a_new_private_directory_has_only_the_allowed_principals(tmp_path):
    directory = ensure_private_directory(tmp_path / "private")

    assert_only_allowed_principals(directory)
    assert all(not entry.flags & 0x10 for entry in read_acl(directory).entries), "no inherited"
    assert check_path(directory, Level.PRIVATE) == []


@windows_only
def test_an_existing_unsafe_directory_is_refused_and_left_exactly_as_it_was(unsafe_directory):
    before = icacls_text(unsafe_directory)

    with pytest.raises(UnsafePermissionsError) as caught:
        ensure_private_directory(unsafe_directory)

    assert icacls_text(unsafe_directory) == before
    assert SID_USERS in {p.principal for p in caught.value.problems}


@windows_only
def test_verification_never_changes_permissions(unsafe_directory):
    before = icacls_text(unsafe_directory)

    check_path(unsafe_directory, Level.PRIVATE, check_ancestors=True)
    with pytest.raises(UnsafePermissionsError):
        verify_or_raise([(unsafe_directory, Level.NO_FOREIGN_WRITE)])

    assert icacls_text(unsafe_directory) == before


@windows_only
def test_an_existing_safe_directory_is_accepted_without_changes(tmp_path):
    directory = ensure_private_directory(tmp_path / "safe")
    before = icacls_text(directory)

    assert ensure_private_directory(directory) == directory
    assert icacls_text(directory) == before


@windows_only
def test_a_junction_is_refused_even_if_its_target_is_private(tmp_path):
    target = ensure_private_directory(tmp_path / "target")
    link = tmp_path / "link"
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, check=False
    )
    assert completed.returncode == 0, completed.stderr

    with pytest.raises(UnsafePermissionsError) as caught:
        ensure_private_directory(link)

    assert [p.kind for p in caught.value.problems] == ["reparse_point"]


@windows_only
def test_the_current_user_keeps_full_working_access_to_a_private_directory(tmp_path):
    directory = ensure_private_directory(tmp_path / "work")

    file = directory / "note.txt"
    file.write_text("hello")
    assert file.read_text() == "hello"
    (directory / "sub").mkdir()
    file.rename(directory / "sub" / "moved.txt")
    database = directory / "app.db"
    with contextlib.closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE t (x)")
        connection.execute("INSERT INTO t VALUES (1)")
        connection.commit()
    with contextlib.closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT x FROM t").fetchone() == (1,)
    (directory / "sub" / "moved.txt").unlink()
    (directory / "sub").rmdir()
    database.unlink()


# ---------- what other real accounts can do (Windows access check) ----------


def ordinary_accounts() -> list[tuple[str, str]]:
    try:
        return filesystem._local_ordinary_accounts()
    except (OSError, ValueError):
        return []


@windows_only
def test_other_ordinary_accounts_have_no_access_to_a_new_private_directory(tmp_path):
    accounts = ordinary_accounts()
    if not accounts:
        pytest.skip("no other ordinary local account on this machine")
    directory = ensure_private_directory(tmp_path / "private")

    evaluated = 0
    for name, sid in accounts:
        try:
            mask = filesystem.effective_access(directory, sid)
        except OSError:
            continue
        evaluated += 1
        assert mask & ANY_RIGHTS == 0, f"{name} has access 0x{mask:08x}"
    if not evaluated:
        pytest.skip("Windows could not evaluate any other account")


@windows_only
def test_the_access_check_can_detect_an_unsafe_directory(unsafe_directory):
    """Positive control: without it, 'no access' results above would prove nothing."""
    results = []
    for _name, sid in ordinary_accounts():
        try:
            results.append(filesystem.effective_access(unsafe_directory, sid))
        except OSError:
            continue
    if not any(mask & WRITE_RIGHTS for mask in results):
        pytest.skip("no evaluable ordinary account is a member of Users on this machine")
    assert any(mask & WRITE_RIGHTS for mask in results)


# ---------- startup fails closed ----------


def enforce_settings(tmp_path, **extra) -> Settings:
    return Settings(
        database_url=f"sqlite:///{(tmp_path / 'db' / 'app.db').as_posix()}",
        file_permission_policy="enforce",
        api_token_hash="a" * 64,
        **extra,
    )


@windows_only
def test_startup_refuses_to_run_with_unsafe_permissions(tmp_path, unsafe_directory, monkeypatch, capsys):
    monkeypatch.setattr(
        "app.main.protected_targets", lambda root, url: [(unsafe_directory, Level.NO_FOREIGN_WRITE)]
    )

    with pytest.raises(UnsafePermissionsError):
        create_app(enforce_settings(tmp_path))

    output = capsys.readouterr().out
    assert "filesystem_permissions_unsafe" in output
    assert json.dumps(str(unsafe_directory))[1:-1] in output
    assert SID_USERS in output


@windows_only
def test_permission_failures_are_logged_without_secrets(tmp_path, unsafe_directory, monkeypatch, capsys):
    monkeypatch.setattr(
        "app.main.protected_targets", lambda root, url: [(unsafe_directory, Level.NO_FOREIGN_WRITE)]
    )
    secret_hash = "b" * 64
    settings = enforce_settings(tmp_path).model_copy(update={"api_token_hash": secret_hash})

    with pytest.raises(UnsafePermissionsError):
        create_app(settings)

    output = capsys.readouterr().out
    assert secret_hash not in output
    assert "Bearer" not in output


@windows_only
def test_startup_succeeds_when_permissions_are_safe(tmp_path, monkeypatch):
    safe = ensure_private_directory(tmp_path / "safe")
    monkeypatch.setattr("app.main.protected_targets", lambda root, url: [(safe, Level.PRIVATE)])

    assert create_app(enforce_settings(tmp_path)) is not None


@windows_only
def test_startup_creates_the_database_directory_private(tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.protected_targets", lambda root, url: [])
    settings = enforce_settings(tmp_path)

    create_app(settings)

    assert check_path(tmp_path / "db", Level.PRIVATE) == []
    assert_only_allowed_principals(tmp_path / "db")


@windows_only
def test_startup_refuses_an_existing_shared_database_directory(tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.protected_targets", lambda root, url: [])
    shared = tmp_path / "db"
    shared.mkdir()
    grant(shared, SID_USERS)
    before = icacls_text(shared)

    with pytest.raises(UnsafePermissionsError):
        create_app(enforce_settings(tmp_path))

    assert icacls_text(shared) == before


def test_policy_off_skips_verification_entirely(tmp_path, monkeypatch):
    def explode(root, url):
        raise AssertionError("must not be called")

    monkeypatch.setattr("app.main.protected_targets", explode)
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'x.db').as_posix()}", file_permission_policy="off"
    )

    assert create_app(settings) is not None


def test_enforcement_is_the_default():
    assert Settings.model_fields["file_permission_policy"].default == "enforce"


def test_protected_targets_cover_code_config_credentials_and_database(tmp_path):
    targets = dict(
        filesystem.protected_targets(tmp_path, f"sqlite:///{(tmp_path / 'data' / 'g.db').as_posix()}")
    )

    assert targets[tmp_path] is Level.NO_FOREIGN_WRITE
    for name in ("services", "scripts", ".venv"):
        assert targets[tmp_path / name] is Level.NO_FOREIGN_WRITE
    assert targets[tmp_path / ".env"] is Level.PRIVATE
    assert targets[tmp_path / "data"] is Level.PRIVATE
    assert targets[tmp_path / "data" / "g.db"] is Level.PRIVATE
    assert targets[Path(str(tmp_path / "data" / "g.db") + "-wal")] is Level.PRIVATE


def test_in_memory_databases_add_no_paths(tmp_path):
    targets = filesystem.protected_targets(tmp_path, "sqlite:///:memory:")

    assert all(level is Level.NO_FOREIGN_WRITE for _path, level in targets if _path != tmp_path / ".env")


# ---------- the AI and application code cannot change permissions ----------

PERMISSION_CHANGING_TOKENS = [
    "icacls", "takeown", "cacls", "SetNamedSecurityInfo", "SetSecurityInfo", "SetFileSecurity",
    "Set-Acl", "SetSecurityDescriptor", ".chmod(", "os.chmod", "os.chown", "setfacl",
]


def test_only_the_permissions_module_can_change_permissions():
    app_dir = Path(filesystem.__file__).resolve().parents[1]
    offenders = []
    for source in app_dir.rglob("*.py"):
        if source.name == "filesystem.py":
            continue
        text = source.read_text(encoding="utf-8")
        offenders += [f"{source.name}: {token}" for token in PERMISSION_CHANGING_TOKENS if token in text]

    assert offenders == []


def test_the_permissions_module_only_restricts_directories_it_just_created():
    source = Path(filesystem.__file__).read_text(encoding="utf-8")
    body = source[source.index("def ensure_private_directory") : source.index("def audit_tree")]

    assert "directory.mkdir(parents=True)" in body
    assert body.index("mkdir") < body.index("_private_acl_arguments")
    assert source.count("_private_acl_arguments(") == 2, "one definition and one call"


def test_the_model_provider_cannot_run_commands_that_edit_permissions():
    from app.ai.providers.claude_cli import lockdown_arguments

    arguments = lockdown_arguments("system", "")

    assert arguments[arguments.index("--tools") + 1] == ""
    assert "--restricted" in arguments
    assert arguments[arguments.index("--permission-mode") + 1] == "dontAsk"


# ---------- the real project on this machine (opt-in) ----------

host_check = pytest.mark.skipif(
    os.environ.get("GREENLOOP_VERIFY_HOST_PERMISSIONS") != "1" or sys.platform != "win32",
    reason="set GREENLOOP_VERIFY_HOST_PERMISSIONS=1 to check this machine's real project",
)


@host_check
def test_real_project_paths_pass_the_policy():
    database_url = Settings().database_url
    targets = filesystem.protected_targets(REPO_ROOT, database_url)

    verify_or_raise(targets)


@host_check
def test_no_other_ordinary_account_can_modify_the_real_project():
    accounts = ordinary_accounts()
    assert accounts, "expected at least one other ordinary local account to test against"
    targets = [
        (path, level)
        for path, level in filesystem.protected_targets(REPO_ROOT, Settings().database_url)
        if path.exists()
    ]
    evaluated = 0
    for name, sid in accounts:
        for path, level in targets:
            try:
                mask = filesystem.effective_access(path, sid)
            except OSError:
                continue
            evaluated += 1
            assert mask & WRITE_RIGHTS == 0, f"{name} can modify {path}"
            if level is Level.PRIVATE:
                assert mask & ANY_RIGHTS == 0, f"{name} can read {path}"
    assert evaluated > 0


@host_check
def test_the_current_user_keeps_access_to_every_real_protected_path():
    database_url = Settings().database_url
    for path, _level in filesystem.protected_targets(REPO_ROOT, database_url):
        if not path.exists():
            continue
        if path.is_dir():
            probe = path / ".greenloop-permission-probe"
            probe.write_text("ok")
            assert probe.read_text() == "ok"
            probe.unlink()
        else:
            with open(path, "rb") as handle:
                handle.read(1)
    with contextlib.closing(sqlite3.connect(Path(database_url.removeprefix("sqlite:///")))) as db:
        db.execute("SELECT 1").fetchone()


@host_check
def test_the_real_default_sandbox_is_private_and_cannot_be_replaced_by_others():
    from app.ai.providers.claude_cli import default_sandbox_directory

    directory = default_sandbox_directory()

    ensure_private_directory(directory, check_ancestors=True)
    assert check_path(directory, Level.PRIVATE, check_ancestors=True) == []
    for name, sid in ordinary_accounts():
        try:
            mask = filesystem.effective_access(directory, sid)
        except OSError:
            continue
        assert mask & ANY_RIGHTS == 0, f"{name} can access the sandbox"
