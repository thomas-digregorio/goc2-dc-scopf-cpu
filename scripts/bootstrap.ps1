$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ($repo -match '(?i)OneDrive') { throw "Refusing OneDrive path: $repo" }
Set-Location -LiteralPath $repo
git submodule update --init --recursive
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e '.[dev]'

