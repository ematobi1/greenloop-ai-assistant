"""Filesystem permission policy for GreenLoop-owned paths.

Policy: the current Windows user is the only ordinary account that may modify GreenLoop's
files. SYSTEM, Administrators, and TrustedInstaller are allowed because the operating system
and administrators can take control of any file anyway. This module does not defend against a
compromised administrator or SYSTEM account.

Verification only reads permissions. The single place this module writes a permission is
`ensure_private_directory`, which restricts a directory that GreenLoop itself just created.
Existing directories are never modified: unsafe ones are reported and refused.
"""

import ctypes
import enum
import os
import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import structlog

logger = structlog.get_logger()

FILE_READ_DATA = 0x1
FILE_WRITE_DATA = 0x2
FILE_APPEND_DATA = 0x4
FILE_WRITE_EA = 0x10
FILE_DELETE_CHILD = 0x40
FILE_WRITE_ATTRIBUTES = 0x100
DELETE = 0x10000
WRITE_DAC = 0x40000
WRITE_OWNER = 0x80000
SYNCHRONIZE = 0x100000
GENERIC_WRITE = 0x40000000
GENERIC_ALL = 0x10000000
MAXIMUM_ALLOWED = 0x02000000

WRITE_RIGHTS = (
    FILE_WRITE_DATA
    | FILE_APPEND_DATA
    | FILE_WRITE_EA
    | FILE_DELETE_CHILD
    | FILE_WRITE_ATTRIBUTES
    | DELETE
    | WRITE_DAC
    | WRITE_OWNER
    | GENERIC_WRITE
    | GENERIC_ALL
    | MAXIMUM_ALLOWED
)
ANY_RIGHTS = 0xFFFFFFFF & ~SYNCHRONIZE
REPLACE_RIGHTS = FILE_DELETE_CHILD | DELETE | WRITE_DAC | WRITE_OWNER | GENERIC_ALL

OBJECT_INHERIT = 0x1
CONTAINER_INHERIT = 0x2
INHERIT_ONLY = 0x8

SID_SYSTEM = "S-1-5-18"
SID_ADMINISTRATORS = "S-1-5-32-544"
SID_TRUSTED_INSTALLER = "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"
SID_CREATOR_OWNER = "S-1-3-0"
SID_OWNER_RIGHTS = "S-1-3-4"
SID_EVERYONE = "S-1-1-0"
SID_AUTHENTICATED_USERS = "S-1-5-11"
SID_USERS = "S-1-5-32-545"

OS_SIDS = frozenset({SID_SYSTEM, SID_ADMINISTRATORS, SID_TRUSTED_INSTALLER})
PLACEHOLDER_SIDS = frozenset({SID_CREATOR_OWNER, SID_OWNER_RIGHTS})


class Level(enum.Enum):
    NO_FOREIGN_WRITE = "no_foreign_write"
    PRIVATE = "private"


@dataclass(frozen=True)
class AclEntry:
    sid: str
    mask: int
    flags: int = 0
    allow: bool = True


@dataclass(frozen=True)
class AclReport:
    path: str
    owner: str | None
    entries: list[AclEntry] = field(default_factory=list)
    null_dacl: bool = False


@dataclass(frozen=True)
class Problem:
    path: str
    kind: str
    principal: str = ""
    rights: str = ""

    def describe(self) -> str:
        detail = f" ({self.principal}, {self.rights})" if self.principal else ""
        return f"{self.path}: {self.kind}{detail}"


class UnsafePermissionsError(RuntimeError):
    def __init__(self, problems: list[Problem]):
        self.problems = problems
        super().__init__(
            "Unsafe file permissions on GreenLoop paths. Run scripts\\verify-permissions.ps1 "
            "for details and scripts\\secure-permissions.ps1 to fix."
        )


def evaluate(
    report: AclReport,
    level: Level,
    trusted: frozenset[str],
    *,
    ancestor: bool = False,
) -> list[Problem]:
    """Pure policy check over an already-read ACL. Deny entries never excuse an allow entry."""
    problems: list[Problem] = []
    allowed_owners = trusted | OS_SIDS
    if report.owner is not None and report.owner not in allowed_owners and not ancestor:
        problems.append(Problem(report.path, "foreign_owner", report.owner, "owner"))
    if report.null_dacl:
        problems.append(Problem(report.path, "null_dacl", SID_EVERYONE, "full control"))
        return problems

    allowed_principals = trusted | OS_SIDS | PLACEHOLDER_SIDS
    watched = (
        REPLACE_RIGHTS if ancestor else (ANY_RIGHTS if level is Level.PRIVATE else WRITE_RIGHTS)
    )
    for entry in report.entries:
        if not entry.allow or entry.sid in allowed_principals:
            continue
        inherit_only = bool(entry.flags & INHERIT_ONLY)
        if inherit_only and (ancestor or not entry.flags & (OBJECT_INHERIT | CONTAINER_INHERIT)):
            continue
        hit = entry.mask & watched
        if hit:
            if ancestor:
                kind = "replaceable_parent"
            else:
                kind = (
                    "foreign_access"
                    if level is Level.PRIVATE and not hit & WRITE_RIGHTS
                    else "foreign_write"
                )
            problems.append(Problem(report.path, kind, entry.sid, f"mask 0x{hit:08x}"))
    return problems


def ancestors_of(path: Path) -> list[Path]:
    resolved = path.resolve()
    return [parent for parent in resolved.parents]


if os.name == "nt":
    from ctypes import wintypes

    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _advapi32.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    _advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    _advapi32.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    _advapi32.GetAce.restype = wintypes.BOOL
    _advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    _advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    _advapi32.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    _advapi32.ConvertStringSidToSidW.restype = wintypes.BOOL
    _advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    _advapi32.OpenProcessToken.restype = wintypes.BOOL
    _advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _advapi32.GetTokenInformation.restype = wintypes.BOOL
    _kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _kernel32.LocalFree.restype = ctypes.c_void_p
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    class _Acl(ctypes.Structure):
        _fields_ = [
            ("AclRevision", ctypes.c_ubyte),
            ("Sbz1", ctypes.c_ubyte),
            ("AclSize", ctypes.c_ushort),
            ("AceCount", ctypes.c_ushort),
            ("Sbz2", ctypes.c_ushort),
        ]

    class _AceHeader(ctypes.Structure):
        _fields_ = [
            ("AceType", ctypes.c_ubyte),
            ("AceFlags", ctypes.c_ubyte),
            ("AceSize", ctypes.c_ushort),
        ]

    ACE_HEADER_SIZE = ctypes.sizeof(_AceHeader)
    ACCESS_ALLOWED_ACE_TYPE = 0
    ACCESS_DENIED_ACE_TYPE = 1
    SE_FILE_OBJECT = 1
    OWNER_AND_DACL = 0x1 | 0x4
    TOKEN_QUERY = 0x8
    TOKEN_USER_CLASS = 1

    def _sid_to_string(sid_pointer: int) -> str:
        text = wintypes.LPWSTR()
        if not _advapi32.ConvertSidToStringSidW(sid_pointer, ctypes.byref(text)):
            raise OSError(ctypes.get_last_error(), "ConvertSidToStringSid failed")
        try:
            return text.value
        finally:
            _kernel32.LocalFree(ctypes.cast(text, ctypes.c_void_p))

    def current_user_sid() -> str:
        token = wintypes.HANDLE()
        if not _advapi32.OpenProcessToken(
            _kernel32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)
        ):
            raise OSError(ctypes.get_last_error(), "OpenProcessToken failed")
        try:
            needed = wintypes.DWORD()
            _advapi32.GetTokenInformation(token, TOKEN_USER_CLASS, None, 0, ctypes.byref(needed))
            buffer = ctypes.create_string_buffer(needed.value)
            if not _advapi32.GetTokenInformation(
                token, TOKEN_USER_CLASS, buffer, needed, ctypes.byref(needed)
            ):
                raise OSError(ctypes.get_last_error(), "GetTokenInformation failed")
            sid_pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
            return _sid_to_string(sid_pointer)
        finally:
            _kernel32.CloseHandle(token)

    def read_acl(path: Path | str) -> AclReport:
        owner, dacl, descriptor = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
        status = _advapi32.GetNamedSecurityInfoW(
            str(path),
            SE_FILE_OBJECT,
            OWNER_AND_DACL,
            ctypes.byref(owner),
            None,
            ctypes.byref(dacl),
            None,
            ctypes.byref(descriptor),
        )
        if status != 0:
            raise OSError(status, f"cannot read permissions of {path}")
        try:
            owner_sid = _sid_to_string(owner.value) if owner.value else None
            if not dacl.value:
                return AclReport(str(path), owner_sid, [], null_dacl=True)
            acl = ctypes.cast(dacl, ctypes.POINTER(_Acl)).contents
            entries: list[AclEntry] = []
            for index in range(acl.AceCount):
                pointer = ctypes.c_void_p()
                if not _advapi32.GetAce(dacl, index, ctypes.byref(pointer)):
                    raise OSError(ctypes.get_last_error(), "GetAce failed")
                header = _AceHeader.from_address(pointer.value)
                if header.AceType not in (ACCESS_ALLOWED_ACE_TYPE, ACCESS_DENIED_ACE_TYPE):
                    continue
                mask = ctypes.c_uint32.from_address(pointer.value + ACE_HEADER_SIZE).value
                sid = _sid_to_string(pointer.value + ACE_HEADER_SIZE + 4)
                entries.append(
                    AclEntry(sid, mask, header.AceFlags, header.AceType == ACCESS_ALLOWED_ACE_TYPE)
                )
            return AclReport(str(path), owner_sid, entries)
        finally:
            _kernel32.LocalFree(descriptor)

    _authz = ctypes.WinDLL("authz", use_last_error=True)

    class _Luid(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class _AuthzAccessRequest(ctypes.Structure):
        _fields_ = [
            ("DesiredAccess", wintypes.DWORD),
            ("PrincipalSelfSid", ctypes.c_void_p),
            ("ObjectTypeList", ctypes.c_void_p),
            ("ObjectTypeListLength", wintypes.DWORD),
            ("OptionalArguments", ctypes.c_void_p),
        ]

    class _AuthzAccessReply(ctypes.Structure):
        _fields_ = [
            ("ResultListLength", wintypes.DWORD),
            ("GrantedAccessMask", ctypes.POINTER(wintypes.DWORD)),
            ("SaclEvaluationResults", ctypes.POINTER(wintypes.DWORD)),
            ("Error", ctypes.POINTER(wintypes.DWORD)),
        ]

    _authz.AuthzInitializeResourceManager.argtypes = [
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    _authz.AuthzInitializeResourceManager.restype = wintypes.BOOL
    _authz.AuthzInitializeContextFromSid.argtypes = [
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        _Luid,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    _authz.AuthzInitializeContextFromSid.restype = wintypes.BOOL
    _authz.AuthzAccessCheck.argtypes = [
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.POINTER(_AuthzAccessRequest),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_AuthzAccessReply),
        ctypes.c_void_p,
    ]
    _authz.AuthzAccessCheck.restype = wintypes.BOOL
    _authz.AuthzFreeContext.argtypes = [ctypes.c_void_p]
    _authz.AuthzFreeResourceManager.argtypes = [ctypes.c_void_p]

    def effective_access(path: Path | str, account_sid: str) -> int:
        """Access mask Windows would grant `account_sid` on `path`, including group membership.

        Uses the operating system's own access check, so it answers what another account can
        really do without needing that account's password.
        """
        owner, dacl, descriptor = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
        status = _advapi32.GetNamedSecurityInfoW(
            str(path),
            SE_FILE_OBJECT,
            OWNER_AND_DACL,
            ctypes.byref(owner),
            None,
            ctypes.byref(dacl),
            None,
            ctypes.byref(descriptor),
        )
        if status != 0:
            raise OSError(status, f"cannot read permissions of {path}")
        sid, manager, context = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
        try:
            if not _advapi32.ConvertStringSidToSidW(account_sid, ctypes.byref(sid)):
                raise OSError(ctypes.get_last_error(), "invalid SID")
            if not _authz.AuthzInitializeResourceManager(
                0x1, None, None, None, None, ctypes.byref(manager)
            ):
                raise OSError(ctypes.get_last_error(), "AuthzInitializeResourceManager failed")
            if not _authz.AuthzInitializeContextFromSid(
                0, sid, manager, None, _Luid(0, 0), None, ctypes.byref(context)
            ):
                raise OSError(ctypes.get_last_error(), "cannot evaluate this account")
            request = _AuthzAccessRequest(MAXIMUM_ALLOWED, None, None, 0, None)
            granted, error = wintypes.DWORD(), wintypes.DWORD()
            reply = _AuthzAccessReply(1, ctypes.pointer(granted), None, ctypes.pointer(error))
            if not _authz.AuthzAccessCheck(
                0,
                context,
                ctypes.byref(request),
                None,
                descriptor,
                None,
                0,
                ctypes.byref(reply),
                None,
            ):
                raise OSError(ctypes.get_last_error(), "AuthzAccessCheck failed")
            return granted.value
        finally:
            if context.value:
                _authz.AuthzFreeContext(context)
            if manager.value:
                _authz.AuthzFreeResourceManager(manager)
            if sid.value:
                _kernel32.LocalFree(sid)
            _kernel32.LocalFree(descriptor)

else:

    def current_user_sid() -> str:
        return f"uid:{os.geteuid()}"

    def read_acl(path: Path | str) -> AclReport:
        info = os.stat(path)
        entries = [AclEntry(f"uid:{info.st_uid}", 0x1F01FF)]
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            entries.append(AclEntry("posix:group-or-other", FILE_WRITE_DATA))
        if info.st_mode & (stat.S_IRGRP | stat.S_IROTH):
            entries.append(AclEntry("posix:group-or-other", FILE_READ_DATA))
        return AclReport(str(path), f"uid:{info.st_uid}", entries)

    def effective_access(path: Path | str, account_sid: str) -> int:
        raise NotImplementedError("effective access checks need Windows")


def trusted_principals() -> frozenset[str]:
    return frozenset({current_user_sid()})


def _is_link(path: Path) -> bool:
    return path.is_symlink() or (hasattr(os.path, "isjunction") and os.path.isjunction(path))


def check_path(path: Path, level: Level, *, check_ancestors: bool = False) -> list[Problem]:
    trusted = trusted_principals()
    problems: list[Problem] = []
    try:
        if _is_link(path):
            return [Problem(str(path), "reparse_point")]
        problems += evaluate(read_acl(path), level, trusted)
        if check_ancestors:
            for parent in ancestors_of(path):
                problems += evaluate(read_acl(parent), level, trusted, ancestor=True)
    except OSError:
        problems.append(Problem(str(path), "unreadable"))
    return problems


def verify_or_raise(
    targets: list[tuple[Path, Level]], *, check_ancestors_of: Path | None = None
) -> None:
    problems: list[Problem] = []
    for path, level in targets:
        if not path.exists():
            continue
        problems += check_path(path, level, check_ancestors=path == check_ancestors_of)
    if problems:
        logger.error(
            "filesystem_permissions_unsafe",
            problems=[
                {"path": p.path, "kind": p.kind, "principal": p.principal, "rights": p.rights}
                for p in problems
            ],
        )
        raise UnsafePermissionsError(problems)


def protected_targets(repo_root: Path, database_url: str) -> list[tuple[Path, Level]]:
    """Paths checked before GreenLoop starts. Children inherit, so the roots are enough here;
    `python -m app.security.filesystem --deep` walks everything."""
    from sqlalchemy.engine import make_url

    targets: list[tuple[Path, Level]] = [(repo_root, Level.NO_FOREIGN_WRITE)]
    for name in ("services", "scripts", ".venv"):
        targets.append((repo_root / name, Level.NO_FOREIGN_WRITE))
    targets.append((repo_root / ".env", Level.PRIVATE))
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
        database = Path(url.database)
        targets.append((database.parent, Level.PRIVATE))
        for suffix in ("", "-wal", "-shm", "-journal"):
            targets.append((Path(str(database) + suffix), Level.PRIVATE))
    return targets


def _private_acl_arguments(directory: Path) -> list[str]:
    return [
        "icacls",
        str(directory),
        "/inheritance:r",
        "/grant:r",
        f"*{current_user_sid()}:(OI)(CI)F",
        "/grant:r",
        f"*{SID_SYSTEM}:(OI)(CI)F",
        "/grant:r",
        f"*{SID_ADMINISTRATORS}:(OI)(CI)F",
    ]


def ensure_private_directory(directory: Path, *, check_ancestors: bool = False) -> Path:
    """Create `directory` restricted to this user, or verify an existing one. Never edits an
    existing directory: an unsafe one raises so the owner can decide what to do.

    With `check_ancestors`, folders above it must not let other accounts delete or replace it."""
    focus = directory if check_ancestors else None
    if directory.exists() or _is_link(directory):
        verify_or_raise([(directory, Level.PRIVATE)], check_ancestors_of=focus)
        return directory
    directory.mkdir(parents=True)
    if os.name == "nt":
        completed = subprocess.run(  # noqa: S603
            _private_acl_arguments(directory),
            capture_output=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0:
            raise UnsafePermissionsError([Problem(str(directory), "cannot_restrict")])
    else:
        directory.chmod(0o700)
    verify_or_raise([(directory, Level.PRIVATE)], check_ancestors_of=focus)
    return directory


def audit_tree(root: Path, level: Level = Level.NO_FOREIGN_WRITE) -> list[Problem]:
    """Deep check of every file and directory below `root`. Read-only."""
    trusted = trusted_principals()
    problems: list[Problem] = []
    for current, directories, files in os.walk(root):
        for name in [*directories, *files]:
            path = Path(current) / name
            try:
                problems += evaluate(read_acl(path), level, trusted)
            except OSError:
                problems.append(Problem(str(path), "unreadable"))
    return problems


def _local_ordinary_accounts() -> list[tuple[str, str]]:
    """(name, SID) of enabled local accounts that are not administrators and not this user."""
    script = (
        "$admins = (Get-LocalGroupMember -SID S-1-5-32-544).SID.Value;"
        "Get-LocalUser | Where-Object { $_.SID.Value -notin $admins } | "
        "ForEach-Object { '{0}|{1}|{2}' -f $_.Name, $_.SID.Value, $_.Enabled }"
    )
    output = subprocess.run(  # noqa: S603
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    me = current_user_sid()
    accounts = []
    for line in output.splitlines():
        name, sid, _enabled = line.strip().split("|")
        if sid != me:
            accounts.append((name, sid))
    return accounts


def main(argv: list[str] | None = None) -> int:
    import argparse

    from app.config import REPO_ROOT, get_settings

    parser = argparse.ArgumentParser(description="Read-only GreenLoop permission audit")
    parser.add_argument("--deep", action="store_true", help="check every file under the repo")
    parser.add_argument(
        "--effective", action="store_true", help="ask Windows what other accounts can do"
    )
    arguments = parser.parse_args(argv)

    print(f"current user SID: {current_user_sid()}")
    problems: list[Problem] = []
    for path, level in protected_targets(REPO_ROOT, get_settings().database_url):
        if not path.exists():
            print(f"  missing   {path}")
            continue
        found = check_path(path, level, check_ancestors=path == REPO_ROOT)
        problems += found
        print(f"  {'UNSAFE' if found else 'ok    '}    [{level.value}] {path}")
    if arguments.deep:
        deep = audit_tree(REPO_ROOT)
        problems += deep
        print(f"deep audit: {len(deep)} problem(s) in the whole tree")
    if arguments.effective and os.name == "nt":
        print("effective access of other ordinary local accounts (0x0 means no access):")
        for name, sid in _local_ordinary_accounts():
            for path, level in protected_targets(REPO_ROOT, get_settings().database_url):
                if not path.exists():
                    continue
                try:
                    mask = effective_access(path, sid)
                except OSError as err:
                    print(f"  {name:22} could not evaluate {path.name}: {err}")
                    problems.append(Problem(str(path), "cannot_evaluate", name))
                    continue
                write = bool(mask & WRITE_RIGHTS)
                blocked = write or (level is Level.PRIVATE and bool(mask & ANY_RIGHTS))
                verdict = "HAS ACCESS" if blocked else "no access"
                print(f"  {name:22} {verdict:11} 0x{mask:08x} {path.name or path}")
                if blocked:
                    problems.append(
                        Problem(str(path), "effective_access", name, f"mask 0x{mask:08x}")
                    )
    for problem in problems:
        print("PROBLEM", problem.describe())
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
