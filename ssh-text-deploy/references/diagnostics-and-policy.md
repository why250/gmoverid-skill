# Diagnostics and Policy Boundaries

## Confirm the actual failure

Inspect metadata and a short hexadecimal prefix without printing the file:

```bash
file /authorized/path/runner.py
wc -c /authorized/path/runner.py
od -An -tx1 -N32 /authorized/path/runner.py
```

The ASCII prefix `%TSD-Header-###%` has this 16-byte hexadecimal form:

```text
255453442d4865616465722d23232325
```

If a transferred Python file begins with that prefix, Python may report
non-UTF-8 source bytes. Do not attempt to reverse, decrypt, or remove the
wrapper. Determine the administrator-approved transfer path.

Other common causes must be ruled out:

- `Exec format error` with valid Python text usually means a CRLF-damaged
  shebang or missing interpreter, not encryption.
- A UTF-8 error without the wrapper may be a legitimate legacy encoding.
- A hash mismatch can come from intentional CRLF normalization; compare the
  bytes actually transmitted.

## Persistent deployment

The bundled PowerShell sender writes through SSH stdin, creates a temporary
file beside the destination, sets `0644` or `0755`, atomically renames it, and
compares local/remote SHA-256 hashes. Use `-WhatIf` first.

This is appropriate only when remote shell creation is an approved operation.
It must not be used to evade controls that intentionally prohibit the payload
or destination.

## One-off execution without a remote source file

When policy permits stdin execution and the user explicitly requests it:

```powershell
Get-Content .\runner.py -Raw |
  ssh approved-host 'cd /authorized/project && python3 -'
```

This is less reproducible than a verified persistent deployment. Preserve the
local source and command record, and never pipe unreviewed or secret-bearing
content.

## Post-deployment checks

Use checks appropriate to the file type:

```bash
python3 /authorized/path/runner.py --help
bash -n /authorized/path/script.sh
shasum -a 256 /authorized/path/document.md
```

For Python scripts, prefer `python3 file.py --help` or `ast.parse` over running
the full workload. A deployment check must not trigger an unrelated external
mutation.
