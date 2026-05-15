#Requires -Version 5.1
<#
.SYNOPSIS
  Мерджит settings.snippet.json в ~/.claude/settings.json для установки
  4 плагинов Claude Code (superpowers / code-review / claude-mem / context-mode).
#>

$ErrorActionPreference = "Stop"

$ClaudeHome = Join-Path $HOME ".claude"
$Settings   = Join-Path $ClaudeHome "settings.json"
$Snippet    = Join-Path $PSScriptRoot "settings.snippet.json"

if (-not (Test-Path $ClaudeHome)) {
    New-Item -ItemType Directory -Path $ClaudeHome | Out-Null
    Write-Host "created $ClaudeHome"
}

$snippetJson = Get-Content $Snippet -Raw | ConvertFrom-Json

if (Test-Path $Settings) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backup = "$Settings.bak.$stamp"
    Copy-Item $Settings $backup
    Write-Host "backup: $backup"
    $current = Get-Content $Settings -Raw | ConvertFrom-Json
} else {
    $current = [pscustomobject]@{}
}

function Merge-Object {
    param($target, $source)
    foreach ($prop in $source.PSObject.Properties) {
        if ($target.PSObject.Properties.Name -contains $prop.Name -and
            $target.$($prop.Name) -is [pscustomobject] -and
            $prop.Value -is [pscustomobject]) {
            Merge-Object $target.$($prop.Name) $prop.Value
        } else {
            if ($target.PSObject.Properties.Name -contains $prop.Name) {
                $target.$($prop.Name) = $prop.Value
            } else {
                $target | Add-Member -NotePropertyName $prop.Name -NotePropertyValue $prop.Value
            }
        }
    }
}

Merge-Object $current $snippetJson

$current | ConvertTo-Json -Depth 32 | Set-Content -Path $Settings -Encoding UTF8
Write-Host "updated: $Settings"

Write-Host ""
Write-Host "next steps in Claude Code:" -ForegroundColor Cyan
Write-Host "  /plugin list      # должны быть 4 плагина enabled"
Write-Host "  /skills           # кастомные + плагинные скиллы"
Write-Host ""
Write-Host "если плагины не появились — перезапустите Claude Code."
