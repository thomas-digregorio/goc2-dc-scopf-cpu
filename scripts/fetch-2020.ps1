$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ($repo -match '(?i)OneDrive') { throw "Refusing OneDrive path: $repo" }
$raw = Join-Path $repo 'data\raw'
$archive = Join-Path $raw 'Challenge_2_Sandbox_Data_C2S7_Scenarios.zip'
$extract = Join-Path $raw 'extracted'
New-Item -ItemType Directory -Force -Path $raw, $extract | Out-Null
if (-not (Test-Path -LiteralPath $archive)) {
  Invoke-WebRequest -Uri 'https://data.openei.org/files/6197/Challenge_2_Sandbox_Data_C2S7_Scenarios.zip' -OutFile $archive
}
$actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()
$expected = 'db4abfae18a97bc97dd30670308668bbd15872ca8ecb0b3b68739c5e0563945e'
if ($actual -ne $expected) { throw "Archive SHA256 mismatch: $actual" }
tar -xf $archive -C $extract 'C2S7N02020/scenario_001'
if ($LASTEXITCODE -ne 0) { throw "Failed to extract C2S7N02020/scenario_001" }
Write-Host "Verified $archive and extracted C2S7N02020/scenario_001"
