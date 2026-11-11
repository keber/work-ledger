<#
.SYNOPSIS
Removes the scheduled task \WorkLedger\WeeklyDigest registered by install-weekly-task.ps1.

.EXAMPLE
.\scripts\uninstall-weekly-task.ps1 -WhatIf
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$TaskPath = '\WorkLedger\'
$TaskName = 'WeeklyDigest'
$target = "$TaskPath$TaskName"

$task = Get-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Output "$target is not installed; nothing to remove."
    exit 0
}

if ($PSCmdlet.ShouldProcess($target, 'Unregister scheduled task')) {
    try {
        Unregister-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -Confirm:$false
    }
    catch {
        Write-Error "uninstall-weekly-task: cannot remove ${target}: $($_.Exception.Message)" -ErrorAction Continue
        exit 1
    }
    Write-Output "Removed $target."
}
exit 0
