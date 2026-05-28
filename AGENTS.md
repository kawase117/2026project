# AGENTS.md

**Rule:** In each command, **define → use**. Do **not** escape `$`. Use generic `'path/to/file.ext'`.

**Recommended project context:** If `CLAUDE.md` or `CONTEXT.md` exists in the repository root, read them at the start of work and reflect them in decisions.
- Use `CLAUDE.md` as project-specific working guidance.
- Use `CONTEXT.md` as background knowledge and current project context.
- If guidance conflicts, follow direct user instructions first, then `AGENTS.md`, then `CLAUDE.md`, then `CONTEXT.md`.

**Plan-First Review Rule (Claude plan handoff):**
- When the user provides an implementation plan (including plans authored by Claude), do **not** start coding immediately.
- First respond with a short pre-check that explicitly states:
  1. whether there are objections/risks, and
  2. what confirmations or assumptions are needed.
- Start implementation only after this pre-check is provided (or after user says to proceed).

**Instinct Sync Rule (ClaudeCode -> Codex execution loop):**
- At start of work, refresh active instincts with:
  - `venv\Scripts\python.exe scripts/compile_instincts.py`
  - or `powershell -File scripts/refresh_instincts.ps1`
- During long sessions, rerun refresh before major decisions or every 15-20 minutes.
- Read `document/instincts/ACTIVE_INSTINCTS.jsonl` first (canonical); use `ACTIVE_INSTINCTS.md` as quick view; open raw `document/instincts/*.yaml` only when detail is missing.

---

## 1) READ (UTF‑8 no BOM, line‑numbered)

```bash
bash -lc 'powershell -NoLogo -Command "
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false);
Set-Location -LiteralPath (Convert-Path .);
function Get-Lines { param([string]$Path,[int]$Skip=0,[int]$First=40)
  $enc=[Text.UTF8Encoding]::new($false)
  $text=[IO.File]::ReadAllText($Path,$enc)
  if($text.Length -gt 0 -and $text[0] -eq [char]0xFEFF){ $text=$text.Substring(1) }
  $ls=$text -split \"`r?`n\"
  for($i=$Skip; $i -lt [Math]::Min($Skip+$First,$ls.Length); $i++){ \"{0:D4}: {1}\" -f ($i+1), $ls[$i] }
}
Get-Lines -Path \"path/to/file.ext\" -First 120 -Skip 0
"'
```

---

## 2) WRITE (UTF‑8 no BOM, atomic replace, backup)

```bash
bash -lc 'powershell -NoLogo -Command "
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false);
Set-Location -LiteralPath (Convert-Path .);
function Write-Utf8NoBom { param([string]$Path,[string]$Content)
  $dir = Split-Path -Parent $Path
  if (-not (Test-Path $dir)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
  }
  $tmp = [IO.Path]::GetTempFileName()
  try {
    $enc = [Text.UTF8Encoding]::new($false)
    [IO.File]::WriteAllText($tmp,$Content,$enc)
    Move-Item $tmp $Path -Force
  }
  finally {
    if (Test-Path $tmp) {
      Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    }
  }
}
$file = "path/to/your_file.ext"
$enc  = [Text.UTF8Encoding]::new($false)
$old  = (Test-Path $file) ? ([IO.File]::ReadAllText($file,$enc)) : ''
Write-Utf8NoBom -Path $file -Content ($old+"`nYOUR_TEXT_HERE`n")
"'
```
