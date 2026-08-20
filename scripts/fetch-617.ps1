$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ($repo -match '(?i)OneDrive') { throw "Refusing OneDrive path: $repo" }
$raw = Join-Path $repo 'data\raw'
$archive = Join-Path $raw 'Challenge_2_Sandbox_Data_C2S6N00617_Scenarios.zip'
$extract = Join-Path $raw 'extracted'
New-Item -ItemType Directory -Force -Path $raw, $extract | Out-Null
if (-not (Test-Path -LiteralPath $archive)) {
  Invoke-WebRequest -Uri 'https://data.openei.org/files/6197/Challenge_2_Sandbox_Data_C2S6N00617_Scenarios.zip' -OutFile $archive
}
$actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()
$expected = 'dbc25ca01a1691cc8e95b40652eb6d5c1480d483fbecb4e9b59af61e4510deea'
if ($actual -ne $expected) { throw "Archive SHA256 mismatch: $actual" }
Expand-Archive -LiteralPath $archive -DestinationPath $extract -Force
Write-Host "Verified and extracted $archive"

