# ============================================================
#  Laptop-runner voor de Oud-West Oasis Airbnb-bot
#  Neemt de bot over van de cloud zolang de laptop aan staat.
#  Draait ~elke minuut via de Taakplanner, vensterloos (zie .vbs).
#
#  Per ronde:
#   1) secrets laden (gitignored)        4) warm-up bij overname (anti-dubbel)
#   2) heartbeat lezen (was ik actief?)  5) gedeelde state pullen
#   3) heartbeat verversen (=claim)      6) bot draaien als 'laptop'
#                                        7) gewijzigde state pushen
# ============================================================
$ErrorActionPreference = "Continue"
$dir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $dir
$logFile = Join-Path $dir "laptop_runner.log"
function Log($m) {
    "$([DateTime]::Now.ToString('yyyy-MM-dd HH:mm:ss'))  $m" |
        Out-File -FilePath $logFile -Append -Encoding utf8
}

# Taakplanner heeft soms een kale PATH: git/gh/python weer beschikbaar maken.
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path","User")

$repo = "OudWestOasis/oud-west-airbnb-bot"

# 1) Secrets uit gitignored bestand (token/chat-id nooit in de repo).
$secrets = Join-Path $dir "laptop_secrets.ps1"
if (-not (Test-Path $secrets)) { Log "GEEN laptop_secrets.ps1 gevonden - gestopt."; exit 0 }
. $secrets                       # zet $env:TELEGRAM_BOT_TOKEN en $env:TELEGRAM_CHAT_ID
$env:RUN_LOCATION = "laptop"

# 2) Huidige heartbeat lezen: was de laptop net al actief?
$old = ""
try { $old = (gh api "repos/$repo/actions/variables/LAPTOP_HEARTBEAT" -q ".value" 2>$null) } catch {}
$wasFresh = $false
if ($old) {
    try {
        $age = ([DateTime]::UtcNow - ([DateTime]::Parse($old)).ToUniversalTime()).TotalSeconds
        if ($age -lt 180) { $wasFresh = $true }
    } catch {}
}

# 3) Heartbeat verversen (= "ik claim deze ronde"). Lukt dit niet (geen internet /
#    gh-fout), dan NIET draaien: anders zou de cloud me niet zien en dubbel sturen.
$now = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
gh variable set LAPTOP_HEARTBEAT --repo $repo --body $now 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { Log "Heartbeat verversen mislukt - ronde overgeslagen (anti-dubbel)."; exit 0 }

# 4) Warm-up: neem ik nu nét over van de cloud (heartbeat was niet vers)? Dan deze
#    ronde NIET verwerken. De cloud-run die nu eventueel loopt maakt 'm af; vanaf
#    de volgende minuut ziet de cloud mijn verse heartbeat en gaat hij stand-by.
if (-not $wasFresh) { Log "Overname van cloud - warm-up, deze ronde overgeslagen (anti-dubbel)."; exit 0 }

# 5) Gedeelde state ophalen (best effort; een git-fout mag de bot niet stoppen).
try { git pull --rebase --autostash origin main 2>$null | Out-Null } catch { Log "git pull overgeslagen: $_" }

# 6) De bot draaien als 'laptop' (altijd draaien, geen stand-by-check).
try { python oasis_airbnb_bot.py tick 2>&1 | ForEach-Object { Log $_ } }
catch { Log "bot-fout: $_" }

# 7) Gewijzigde state terugschrijven (alleen als er echt iets veranderd is).
git add airbnb_state.json 2>$null
git diff --cached --quiet 2>$null
if ($LASTEXITCODE -ne 0) {
    git commit -m "Update state (laptop) [skip ci]" 2>$null | Out-Null
    for ($i = 0; $i -lt 3; $i++) {
        git pull --rebase --autostash origin main 2>$null | Out-Null
        git push 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { Log "State gepusht."; break }
        Start-Sleep 3
    }
}
