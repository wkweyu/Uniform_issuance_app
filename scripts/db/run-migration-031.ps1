param(
    [Parameter(Mandatory = $false)]
    [ValidateSet('staging', 'production')]
    [string]$Target = 'staging',

    [Parameter(Mandatory = $false)]
    [string]$EnvFile,

    [Parameter(Mandatory = $false)]
    [switch]$SkipBackup,

    [Parameter(Mandatory = $false)]
    [switch]$NoPause
)

$ErrorActionPreference = 'Stop'

function Get-ScriptRoot {
    if ($PSScriptRoot) { return $PSScriptRoot }
    return Split-Path -Parent $MyInvocation.MyCommand.Path
}

function Parse-DotEnv {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Env file not found: $Path"
    }

    $map = @{}
    Get-Content -LiteralPath $Path | ForEach-Object {
        $line = $_.Trim()
        if ([string]::IsNullOrWhiteSpace($line)) { return }
        if ($line.StartsWith('#')) { return }
        $eq = $line.IndexOf('=')
        if ($eq -lt 1) { return }

        $key = $line.Substring(0, $eq).Trim()
        $val = $line.Substring($eq + 1).Trim()

        if (($val.StartsWith('"') -and $val.EndsWith('"')) -or ($val.StartsWith("'") -and $val.EndsWith("'"))) {
            $val = $val.Substring(1, $val.Length - 2)
        }

        $map[$key] = $val
    }

    return $map
}

function Require-Command {
    param([Parameter(Mandatory = $true)][string]$Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' is not installed or not in PATH."
    }
}

function Get-PythonCommand {
    param([Parameter(Mandatory = $true)][string]$RepoRoot)

    $venvPython = Join-Path $RepoRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $venvPython) {
        return [pscustomobject]@{ Exe = $venvPython; PrefixArgs = @() }
    }

    $pythonCmd = Get-Command 'python' -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        return [pscustomobject]@{ Exe = $pythonCmd.Source; PrefixArgs = @() }
    }

    $pyLauncher = Get-Command 'py' -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        return [pscustomobject]@{ Exe = $pyLauncher.Source; PrefixArgs = @('-3') }
    }

    return $null
}

function Require-Value {
    param(
        [Parameter(Mandatory = $true)][hashtable]$Map,
        [Parameter(Mandatory = $true)][string]$Key,
        [Parameter(Mandatory = $false)][string]$Default
    )

    if ($Map.ContainsKey($Key) -and -not [string]::IsNullOrWhiteSpace($Map[$Key])) {
        return $Map[$Key]
    }
    if ($PSBoundParameters.ContainsKey('Default')) {
        return $Default
    }
    throw "Missing required key '$Key' in env file."
}

function Invoke-MySql {
    param(
        [Parameter(Mandatory = $true)][string]$DbHost,
        [Parameter(Mandatory = $true)][string]$DbPort,
        [Parameter(Mandatory = $true)][string]$DbUser,
        [Parameter(Mandatory = $true)][string]$DbPassword,
        [Parameter(Mandatory = $true)][string]$DbName,
        [Parameter(Mandatory = $false)][string]$Sql,
        [Parameter(Mandatory = $false)][string]$SqlFile
    )

    if ($script:UseMysqlCli) {
        $env:MYSQL_PWD = $DbPassword
        try {
            if ($SqlFile) {
                & mysql "--host=$DbHost" "--port=$DbPort" "--user=$DbUser" "$DbName" '--batch' '--raw' '--skip-column-names' '--execute=SELECT 1;' | Out-Null
                Get-Content -LiteralPath $SqlFile -Raw | & mysql "--host=$DbHost" "--port=$DbPort" "--user=$DbUser" "$DbName"
                if ($LASTEXITCODE -ne 0) { throw "mysql failed while executing file: $SqlFile" }
                return
            }

            if ($Sql) {
                & mysql "--host=$DbHost" "--port=$DbPort" "--user=$DbUser" "$DbName" '--batch' '--raw' '--skip-column-names' "--execute=$Sql"
                if ($LASTEXITCODE -ne 0) { throw "mysql failed for SQL query." }
                return
            }
        }
        finally {
            Remove-Item Env:MYSQL_PWD -ErrorAction SilentlyContinue
        }
    }
    else {
        $args = @()
        $args += $script:PythonCommand.PrefixArgs
        $args += @(
            $script:PythonRunner,
            '--host', $DbHost,
            '--port', $DbPort,
            '--user', $DbUser,
            '--password', $DbPassword,
            '--database', $DbName
        )

        if ($SqlFile) {
            & $script:PythonCommand.Exe @args '--file' $SqlFile
            if ($LASTEXITCODE -ne 0) { throw "PyMySQL execution failed while executing file: $SqlFile" }
            return
        }

        if ($Sql) {
            & $script:PythonCommand.Exe @args '--query' $Sql
            if ($LASTEXITCODE -ne 0) { throw "PyMySQL execution failed for SQL query." }
            return
        }
    }

    throw 'Invoke-MySql requires either -Sql or -SqlFile.'
}

function Invoke-MySqlDump {
    param(
        [Parameter(Mandatory = $true)][string]$DbHost,
        [Parameter(Mandatory = $true)][string]$DbPort,
        [Parameter(Mandatory = $true)][string]$DbUser,
        [Parameter(Mandatory = $true)][string]$DbPassword,
        [Parameter(Mandatory = $true)][string]$DbName,
        [Parameter(Mandatory = $true)][string]$OutFile
    )

    $env:MYSQL_PWD = $DbPassword
    try {
        & mysqldump "--host=$DbHost" "--port=$DbPort" "--user=$DbUser" '--single-transaction' '--routines' '--triggers' "$DbName" > $OutFile
        if ($LASTEXITCODE -ne 0) {
            throw "mysqldump failed."
        }
    }
    finally {
        Remove-Item Env:MYSQL_PWD -ErrorAction SilentlyContinue
    }
}

$scriptRoot = Get-ScriptRoot
$repoRoot = Resolve-Path (Join-Path $scriptRoot '..\..')
$migrationFile = Join-Path $repoRoot 'migrations\031_harden_fee_payment_tenancy.sql'

if (-not (Test-Path -LiteralPath $migrationFile)) {
    throw "Migration file not found: $migrationFile"
}

if (-not $EnvFile) {
    $envFileName = if ($Target -eq 'production') { '.env.production' } else { '.env.staging' }
    $EnvFile = Join-Path $repoRoot $envFileName
}

if (-not (Test-Path -LiteralPath $EnvFile)) {
    $exampleCandidate = "$EnvFile.example"
    $genericExample = Join-Path $repoRoot '.env.example'

    $hintLines = @()
    $hintLines += "Env file not found: $EnvFile"
    if (Test-Path -LiteralPath $exampleCandidate) {
        $hintLines += "Create it with: Copy-Item '$exampleCandidate' '$EnvFile'"
    }
    elseif (Test-Path -LiteralPath $genericExample) {
        $hintLines += "Create it with: Copy-Item '$genericExample' '$EnvFile'"
    }
    $hintLines += "Then update DB_HOST, DB_USER, DB_PASSWORD, DB_NAME, DB_PORT."
    $hintLines += "Or pass an explicit file using -EnvFile <path>."
    throw ($hintLines -join [Environment]::NewLine)
}

$envMap = Parse-DotEnv -Path $EnvFile

$dbHost = Require-Value -Map $envMap -Key 'DB_HOST'
$dbUser = Require-Value -Map $envMap -Key 'DB_USER'
$dbPass = Require-Value -Map $envMap -Key 'DB_PASSWORD'
$dbName = Require-Value -Map $envMap -Key 'DB_NAME'
$dbPort = Require-Value -Map $envMap -Key 'DB_PORT' -Default '3306'

$script:UseMysqlCli = $null -ne (Get-Command 'mysql' -ErrorAction SilentlyContinue)
$script:PythonCommand = $null
$script:PythonRunner = Join-Path $scriptRoot 'mysql_exec.py'

if (-not $script:UseMysqlCli) {
    if (-not (Test-Path -LiteralPath $script:PythonRunner)) {
        throw "MySQL CLI not found and Python fallback script missing: $script:PythonRunner"
    }
    $script:PythonCommand = Get-PythonCommand -RepoRoot $repoRoot
    if (-not $script:PythonCommand) {
        throw "MySQL CLI not found in PATH, and no Python runtime was found for PyMySQL fallback. Install mysql client or Python."
    }
}

if (-not $SkipBackup) {
    Require-Command -Name 'mysqldump'
}

$timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$backupDir = Join-Path $repoRoot 'backups'
if (-not (Test-Path -LiteralPath $backupDir)) {
    New-Item -ItemType Directory -Path $backupDir | Out-Null
}
$backupFile = Join-Path $backupDir ("{0}_before_031_{1}.sql" -f $Target, $timestamp)

Write-Host "Target: $Target" -ForegroundColor Cyan
Write-Host "Env file: $EnvFile" -ForegroundColor Cyan
Write-Host "DB: $dbUser@${dbHost}:$dbPort/$dbName" -ForegroundColor Cyan
Write-Host "Migration: $migrationFile" -ForegroundColor Cyan
if ($script:UseMysqlCli) {
    Write-Host "Execution mode: mysql CLI" -ForegroundColor Cyan
}
else {
    Write-Host "Execution mode: PyMySQL fallback ($($script:PythonCommand.Exe))" -ForegroundColor Yellow
}

Write-Host "`n[1/4] Connectivity check..." -ForegroundColor Yellow
$version = Invoke-MySql -DbHost $dbHost -DbPort $dbPort -DbUser $dbUser -DbPassword $dbPass -DbName $dbName -Sql 'SELECT VERSION();'
Write-Host "MySQL version: $version" -ForegroundColor Green

if (-not $SkipBackup) {
    Write-Host "`n[2/4] Creating backup: $backupFile" -ForegroundColor Yellow
    Invoke-MySqlDump -DbHost $dbHost -DbPort $dbPort -DbUser $dbUser -DbPassword $dbPass -DbName $dbName -OutFile $backupFile
    Write-Host "Backup complete." -ForegroundColor Green
}
else {
    Write-Host "`n[2/4] Backup skipped by request." -ForegroundColor Yellow
}

Write-Host "`n[3/4] Running migration 031..." -ForegroundColor Yellow
Invoke-MySql -DbHost $dbHost -DbPort $dbPort -DbUser $dbUser -DbPassword $dbPass -DbName $dbName -SqlFile $migrationFile
Write-Host "Migration executed." -ForegroundColor Green

Write-Host "`n[4/4] Running post-checks..." -ForegroundColor Yellow
$checks = @(
    "SHOW COLUMNS FROM fee_ledger LIKE 'school_id';",
    "SHOW COLUMNS FROM fee_payments LIKE 'school_id';",
    "SHOW COLUMNS FROM fee_receipts LIKE 'school_id';",
    "SHOW COLUMNS FROM fee_payment_allocations LIKE 'school_id';",
    "SHOW COLUMNS FROM fee_reallocation_log LIKE 'school_id';",
    "SELECT COUNT(*) AS missing_fee_ledger_school_id FROM fee_ledger WHERE school_id IS NULL;",
    "SELECT COUNT(*) AS missing_fee_payments_school_id FROM fee_payments WHERE school_id IS NULL;",
    "SELECT COUNT(*) AS missing_fee_receipts_school_id FROM fee_receipts WHERE school_id IS NULL;",
    "SELECT COUNT(*) AS missing_fee_payment_allocations_school_id FROM fee_payment_allocations WHERE school_id IS NULL;",
    "SELECT COUNT(*) AS missing_fee_reallocation_log_school_id FROM fee_reallocation_log WHERE school_id IS NULL;"
)

foreach ($sql in $checks) {
    Write-Host "`nSQL> $sql" -ForegroundColor DarkCyan
    Invoke-MySql -DbHost $dbHost -DbPort $dbPort -DbUser $dbUser -DbPassword $dbPass -DbName $dbName -Sql $sql | Out-Host
}

Write-Host "`nMigration 031 completed successfully for '$Target'." -ForegroundColor Green
if (-not $SkipBackup) {
    Write-Host "Backup file: $backupFile" -ForegroundColor Green
}

if (-not $NoPause) {
    Write-Host "`nPress Enter to close..." -ForegroundColor DarkGray
    [void][System.Console]::ReadLine()
}
