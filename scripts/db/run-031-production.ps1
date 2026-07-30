$ErrorActionPreference = 'Stop'
$root = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
& (Join-Path $root 'run-migration-031.ps1') -Target production -EnvFile (Join-Path (Resolve-Path (Join-Path $root '..\..')) '.env.production')
