---
name: ssh-text-deploy
description: "Deploys authorized UTF-8 text files to managed SSH hosts through standard input when scp/SFTP transforms, wraps, or corrupts text content. Use only when the user controls or is authorized to write the exact remote path and server policy permits shell-created files; do not use to defeat access controls, transfer binaries or secrets, or evade an explicit organizational prohibition."
---

# SSH Text Deployment Skill

Use this skill for text-file integrity problems on an authorized SSH target,
not as a generic security-control bypass. A transfer product may intentionally
wrap files received through `scp`; if the applicable policy also prohibits
shell-created files, stop and ask the administrator for the approved channel.

## Required boundary

Before writing, establish all of the following:

- the user authorized the exact host and destination path;
- SSH access already exists through the user's configuration;
- the payload is UTF-8 text, not a binary, archive, credential, key, or secret;
- server policy permits a remote shell process to create that file.

Authorization for one path does not authorize a broader directory or another
host. Do not decrypt wrapped content, disable endpoint tooling, or modify
security configuration.

## Workflow

1. Diagnose read-only: inspect the remote file type, first bytes, and hashes.
   A `%TSD-Header-###%` prefix is one known wrapper signature, not the only
   possible cause of corruption.
2. Prefer the organization's approved transfer method. Use SSH stdin only when
   shell creation is permitted.
3. Run [`scripts/send_text_over_ssh.ps1`](scripts/send_text_over_ssh.ps1) with
   `-WhatIf`, review the exact host/path, then run without `-WhatIf`.
4. Use `-NormalizeLf` for Linux scripts created on Windows and `-Executable`
   only when execution is intended.
5. Require SHA-256 equality and reject a remote TSD header. Then perform a
   format-specific smoke test such as `python3 script.py --help`.

Example:

```powershell
.\scripts\send_text_over_ssh.ps1 `
  -LocalPath .\runner.py `
  -SshHost IC_Server_Local `
  -RemotePath /authorized/project/runner.py `
  -NormalizeLf -Executable -WhatIf

.\scripts\send_text_over_ssh.ps1 `
  -LocalPath .\runner.py `
  -SshHost IC_Server_Local `
  -RemotePath /authorized/project/runner.py `
  -NormalizeLf -Executable
```

For diagnostics, policy boundaries, and a one-off stdin execution pattern,
read [`references/diagnostics-and-policy.md`](references/diagnostics-and-policy.md).

## Scope limits

- The bundled sender accepts a single UTF-8 text file up to 10 MiB by default.
- It validates conservative host/path syntax and writes atomically through a
  temporary file in the destination directory.
- It does not recursively deploy directories, preserve extended attributes,
  transfer symlinks, or support binary payloads.
- It does not broaden the user's authorization or prove policy compliance;
  when policy is unclear, ask rather than assuming.
