<#
.SYNOPSIS
Registers the per-user scheduled task \WorkLedger\WeeklyDigest that runs the weekly digest.

.DESCRIPTION
The task runs scripts\weekly.cmd (refresh, digest, curate, toast) once a week for the current user.
It runs only while the user is logged on (interactive logon), stores no password and runs
without elevation. StartWhenAvailable runs a missed start once the machine is back on.
Re-running the script replaces the task. This changes persistent system configuration:
use -WhatIf first.

.PARAMETER Day
Day of the week, for example Monday.

.PARAMETER Time
Start time, 24-hour HH:mm, local time.

.PARAMETER Python
Python executable name or path. Resolved to a full path at install time. Default: python.

.EXAMPLE
.\scripts\install-weekly-task.ps1 -Day Monday -Time 09:00 -WhatIf
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [System.DayOfWeek]$Day,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^([01][0-9]|2[0-3]):[0-5][0-9]$')]
    [string]$Time,

    [ValidateNotNullOrEmpty()]
    [string]$Python = 'python'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$TaskPath = '\WorkLedger\'
$TaskName = 'WeeklyDigest'

try {
    $projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).ProviderPath
    $wrapper = Join-Path $PSScriptRoot 'weekly.cmd'
    if (-not (Test-Path -LiteralPath $wrapper -PathType Leaf)) {
        throw "wrapper not found: $wrapper"
    }

    $command = Get-Command -Name $Python -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $command) {
        throw "Python executable not found: $Python"
    }
    $pythonPath = $command.Source

    # The action line is parsed by cmd.exe: refuse characters that would change its meaning.
    foreach ($path in @($wrapper, $pythonPath)) {
        if ($path -match '["%^&|<>]') {
            throw "unsupported character in path: $path"
        }
    }

    $at = [datetime]::ParseExact($Time, 'HH:mm', [System.Globalization.CultureInfo]::InvariantCulture)
    $user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $cmdExe = Join-Path $env:SystemRoot 'System32\cmd.exe'

    $action = New-ScheduledTaskAction -Execute $cmdExe `
        -Argument ('/d /s /c ""{0}" "{1}""' -f $wrapper, $pythonPath) `
        -WorkingDirectory $projectRoot
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Day -At $at
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1)
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
}
catch {
    Write-Error "install-weekly-task: $($_.Exception.Message)" -ErrorAction Continue
    exit 1
}

$target = "$TaskPath$TaskName"
if ($PSCmdlet.ShouldProcess($target, "Register weekly task for $user, $Day at $Time, running $wrapper with $pythonPath")) {
    try {
        Register-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -Action $action `
            -Trigger $trigger -Settings $settings -Principal $principal `
            -Description 'work-ledger: weekly pending-work digest and toast' -Force | Out-Null
    }
    catch {
        Write-Error "install-weekly-task: cannot register ${target}: $($_.Exception.Message)" -ErrorAction Continue
        exit 1
    }
    Write-Output "Registered $target ($Day $Time). Log: $(Join-Path $projectRoot 'out\weekly.log')"
}
exit 0
