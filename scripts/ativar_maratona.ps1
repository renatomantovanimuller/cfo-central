# Registra a tarefa agendada CFO-Maratona: roda scripts\maratona.ps1 a cada 20 min até 09:30 de 16/10/2026.
$ErrorActionPreference = "Stop"
$script = Join-Path $PSScriptRoot "maratona.ps1"
$start = (Get-Date).AddMinutes(1)
$duration = ([datetime]"2026-10-16T09:31:00") - $start
if ($duration.TotalMinutes -le 0) { Write-Host "[CFO] O prazo da maratona já passou."; exit 1 }
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`""
$trigger = New-ScheduledTaskTrigger -Once -At $start -RepetitionInterval (New-TimeSpan -Minutes 20) -RepetitionDuration $duration
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 9) `
  -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName "CFO-Maratona" -Action $action -Trigger $trigger -Settings $settings `
  -Description "Retoma a maratona CFO Central quando a cota do Claude volta (até 09:30)" -Force | Out-Null
$next = (Get-ScheduledTask "CFO-Maratona" | Get-ScheduledTaskInfo).NextRunTime
Write-Host "[CFO] Tarefa CFO-Maratona ativa. Próxima verificação: $next. Log: docs\maratona\logs\runner.log"
Write-Host "[CFO] Para desligar: Unregister-ScheduledTask -TaskName CFO-Maratona -Confirm:`$false"
