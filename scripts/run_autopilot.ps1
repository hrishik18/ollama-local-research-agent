# Launch the autonomous research agent via Microsoft `agency` Copilot CLI in autopilot mode.
#
# Usage:
#   .\scripts\run_autopilot.ps1 [-PromptFile <path>] [-MaxContinues <n>] [-Model <name>]

param(
    [string]$PromptFile = "prompts\example_goal.txt",
    [int]$MaxContinues = 300,
    [string]$Model = "claude-opus-4.7"
)

if (-not (Test-Path $PromptFile)) {
    Write-Error "Prompt file not found: $PromptFile"
    exit 1
}

$promptText = Get-Content $PromptFile -Raw

Write-Host "Launching agency copilot in autopilot mode"
Write-Host "  prompt file:    $PromptFile"
Write-Host "  max continues:  $MaxContinues"
Write-Host "  model:          $Model"
Write-Host ""

agency copilot `
  --autopilot `
  --max-autopilot-continues $MaxContinues `
  --model $Model `
  --log-level info `
  -p $promptText
