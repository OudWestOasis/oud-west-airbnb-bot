# Registreert de Taakplanner-taak die de laptop-runner elke minuut vensterloos
# draait (alleen als jij bent ingelogd). Draai dit EENMALIG:
#
#   powershell -ExecutionPolicy Bypass -File register_laptop_task.ps1
#
# Uitzetten kan met:  Unregister-ScheduledTask -TaskName "OudWestOasis-AirbnbLaptop" -Confirm:$false

$ErrorActionPreference = "Stop"
$dir  = Split-Path -Parent $MyInvocation.MyCommand.Definition
$vbs  = Join-Path $dir "run_laptop_hidden.vbs"
$name = "OudWestOasis-AirbnbLaptop"

if (-not (Test-Path (Join-Path $dir "laptop_secrets.ps1"))) {
    Write-Host "LET OP: laptop_secrets.ps1 ontbreekt nog. Maak die eerst aan:" -ForegroundColor Yellow
    Write-Host "  Copy-Item laptop_secrets.example.ps1 laptop_secrets.ps1   (en vul je waarden in)"
}

$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$vbs`""

# Trigger: bij inloggen, daarna elke minuut herhalen (onbeperkt).
$trigger = New-ScheduledTaskTrigger -AtLogOn
$repeat  = (New-ScheduledTaskTrigger -Once -At (Get-Date) `
            -RepetitionInterval (New-TimeSpan -Minutes 1)).Repetition
$trigger.Repetition = $repeat

# Alleen draaien als jij bent ingelogd (zo werken gh-keyring + git-credentials).
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
             -LogonType Interactive -RunLevel Limited

# Geen overlap, op accu mag, en een harde tijdslimiet zodat niets blijft hangen.
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries -StartWhenAvailable `
            -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 4)

Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force `
    -Description "Laptop-runner Oud-West Oasis Airbnb-bot (neemt over van de cloud)" | Out-Null

Write-Host "Taak '$name' geregistreerd: draait elke minuut vensterloos zolang je bent ingelogd." -ForegroundColor Green
Write-Host "Nu meteen 1x starten om te testen..."
Start-ScheduledTask -TaskName $name
