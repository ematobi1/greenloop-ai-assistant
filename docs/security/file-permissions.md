# File permissions policy (Windows)

## Policy

Your Windows account is the only ordinary account that may create, modify, replace, or delete files in GreenLoop's protected paths. Other local users and groups (`Users`, `Everyone`, `Authenticated Users`, other named accounts) get no write access, and no read access to private paths.

Allowed principals on every protected path:

| Principal | Why |
|---|---|
| The current user | Runs GreenLoop |
| `NT AUTHORITY\SYSTEM` | Windows services, backup, antivirus |
| `BUILTIN\Administrators` | Administrators can take ownership of any file, and removing them risks lockout |
| `TrustedInstaller`, `CREATOR OWNER`, `OWNER RIGHTS` | Operating-system placeholders. They grant nothing to other people. |

**This does not protect against a compromised administrator or SYSTEM account.** Either can read or change these files. The policy stops other ordinary local accounts and, through startup checks, alerts you when permissions drift.

## Protected paths

| Path | Level | Why |
|---|---|---|
| Project root, `services\`, `scripts\`, `.venv\` | No foreign write | Code and interpreter. A writable script or DLL is code execution as you. Read access for other accounts is tolerated. |
| `data\` and the SQLite files in it | **Private** | Conversations and audit history |
| `.env` | **Private** | Holds the API token hash and settings |
| `%LOCALAPPDATA%\GreenLoop\claude-sandbox` | **Private** | Working directory of the Claude CLI |

Private means no other ordinary account has any access, read or write.

Not touched: `C:\Users`, `C:\Windows`, your `Documents` folder, `%TEMP%`, and anything else outside the paths above.

## Checks that run before protected operations

`create_app` runs `verify_or_raise` before opening the database, and each Claude CLI run re-verifies its sandbox. A check fails when:

- A foreign principal has write rights (data, append, delete, delete-child, write-attributes, change permissions, take ownership, generic write or all) on a code path, or any access on a private path.
- The owner is not you, Administrators, SYSTEM, or TrustedInstaller. An owner can rewrite permissions.
- The DACL is missing (which means everyone has full control).
- A protected path is a symbolic link or junction, which could redirect it.
- For the project root and the sandbox, a parent folder lets another account delete or replace the folder (`DELETE`, `FILE_DELETE_CHILD`, `WRITE_DAC`, `WRITE_OWNER`). This is why the sandbox lives under `%LOCALAPPDATA%` and not the shared `%TEMP%`.

Deny entries are never used to excuse an allow entry.

On failure GreenLoop logs `filesystem_permissions_unsafe` and stops. It does not change anything. The log lists path, SID, and access mask. It never includes tokens, hashes, or file contents.

## Fixing a failure

Permissions are only changed by you, on purpose:

```powershell
scripts\verify-permissions.ps1            # read-only report
scripts\verify-permissions.ps1 -Deep      # every file under the project
scripts\verify-permissions.ps1 -Effective # what other real accounts can do, per Windows
scripts\secure-permissions.ps1            # dry run: shows current ACLs, changes nothing
scripts\secure-permissions.ps1 -Apply     # backs up ACLs, then restricts data\, .env, the sandbox
```

`-Apply` saves the previous permissions under `%LOCALAPPDATA%\GreenLoop\acl-backups` (restore with `icacls <parent> /restore <file>`) and touches only those three paths. `setup.ps1` runs it for you and says so.

## What GreenLoop itself may change

One thing only: `ensure_private_directory` restricts a directory that GreenLoop has just created (the database folder, the sandbox). An existing directory with unsafe permissions is refused and left exactly as found. A test compares the ACL before and after to prove that.

## AI agents cannot change permissions

- The Claude CLI provider runs with every tool disabled, so a model cannot run `icacls`, `takeown`, or PowerShell.
- No application code path other than `app/security/filesystem.py` calls a permission-changing API. A test scans the source for `icacls`, `takeown`, `Set-Acl`, `SetNamedSecurityInfo`, `chmod`, `chown`, and similar.
- The Tool Gateway (Phase 3 PR 2) must never register a tool that edits ACLs, ownership, or the `GREENLOOP_FILE_PERMISSION_POLICY` setting.
- `secure-permissions.ps1` is run by a person. No component invokes it automatically except `setup.ps1`, which you start.

## Testing

| Test | What it proves |
|---|---|
| 60+ synthetic ACL cases | Every write right for `Users`, `Everyone`, `Authenticated Users`, and a named account is rejected. Read-only is allowed for code and rejected for private paths. Deny entries do not excuse. Owner, null DACL, inherit-only, and parent-folder rules. |
| Real grants with `icacls` | The reader detects real `Users`, `Everyone`, and `Authenticated Users` grants. |
| Windows access check for other accounts | For each enabled local account that is not an administrator, `AuthzAccessCheck` (the operating system's own evaluator, including group membership) reports zero access to a new private directory. A positive control confirms the check can see an unsafe directory. |
| Fail closed | Startup raises on an unsafe path, an unsafe existing database folder, and an unsafe existing sandbox. The ACL is unchanged afterwards and the CLI is never launched. |
| Junctions | A junction is refused as a sandbox or private directory. |
| Your account keeps access | Create, write, rename, delete, and SQLite read and write inside a private directory. |
| Real project (`GREENLOOP_VERIFY_HOST_PERMISSIONS=1`) | On this machine: every protected path passes, no other ordinary account can modify the project or read the private paths, and your account can still write to them. Skipped in CI because a CI runner's folders are not configured this way. |

CI sets `GREENLOOP_FILE_PERMISSION_POLICY=off` for the general suite only. The permission tests construct their own policy and run everywhere.

## Limits

- Group membership is evaluated for local accounts. Domain accounts are outside what was tested.
- The startup check reads the top of each protected tree. Files with their own explicit permissions deeper down need `-Deep`.
- If another account already holds a handle to a file, changing permissions does not close it.
- The read access that the Codex sandbox accounts (`CodexSandboxOffline`, `CodexSandboxOnline`) have to the source code is left in place, since it is not modification. Remove it by breaking inheritance on the project folder if you want the code private too. That would stop Codex from reading the repository.
