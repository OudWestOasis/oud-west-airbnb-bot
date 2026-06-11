# 🔁 Laptop neemt over van de cloud (snellere reacties)

Doel: als je **laptop aan staat**, draait de bot dáár ~elke minuut (snel). Staat
de laptop **uit/dicht**, dan blijft de **cloud** het elke 5 min doen. Nooit
dubbel, overgave gaat beide kanten automatisch.

## Hoe het werkt

- **Heartbeat** = GitHub repo-variabele `LAPTOP_HEARTBEAT` (een tijdstempel). De
  laptop ververst die elke minuut via de API — **geen commit**, dus geen spam.
- **Eén modus `tick`** (commando's + wekelijkse check) draait op beide plekken.
- **Cloud-stand-by:** de cloud-run checkt aan het begin de heartbeat. Vers
  (< 3 min)? Dan slaat de cloud die ronde volledig over (`laptop actief — cloud
  staat stand-by`). Anders draait de cloud normaal.
- **Anti-dubbel bij overname:** de laptop ververst eerst de heartbeat. Neemt hij
  net over (heartbeat was niet vers), dan slaat hij die **eerste** ronde over
  (warm-up), zodat laptop en cloud elkaar nooit overlappen. Lukt het verversen
  niet (geen internet), dan draait de laptop die ronde niet (cloud blijft de
  basis).
- **Gedeelde state:** `airbnb_state.json` staat in de repo. Laptop doet `git
  pull` vóór en `git push` ná — zelfde idempotency (`update_offset`,
  `laatste_week_run`) als de cloud. Niets dubbel, niets gemist.
- **Locatie-onderscheid:** env-var `RUN_LOCATION` = `cloud` of `laptop`. Alleen
  de cloud doet de stand-by-check; de laptop draait altijd.

De **inhoud** van de Telegram-berichten verandert niet — alleen *wie* ze stuurt.

## Eenmalig instellen op de laptop

1. Secrets lokaal zetten (blijft privé, staat in `.gitignore`):
   ```powershell
   cd "C:\Users\joris\Claude\Oud-West Oasis\airbnb-bot-cloud"
   Copy-Item laptop_secrets.example.ps1 laptop_secrets.ps1
   # open laptop_secrets.ps1 en vul je Airbnb-bot-token + chat-id in
   ```
2. De taak registreren (draait elke minuut, vensterloos, alleen als je ingelogd bent):
   ```powershell
   powershell -ExecutionPolicy Bypass -File register_laptop_task.ps1
   ```

Dat is alles. Vanaf nu neemt je laptop het over zodra hij aan staat.

## Testen

- **Cloud gaat stand-by:** zet de heartbeat vers en trigger een cloud-run:
  ```powershell
  gh variable set LAPTOP_HEARTBEAT --repo OudWestOasis/oud-west-airbnb-bot --body (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
  gh workflow run poll.yml
  ```
  In de run-log zie je: `laptop actief — cloud staat stand-by`.
- **Laptop draait:** `Start-ScheduledTask -TaskName OudWestOasis-AirbnbLaptop`
  en kijk in `laptop_runner.log` (eerste keer: warm-up; daarna draait hij echt).

## Uitzetten

- Alleen de laptop-overname stoppen (cloud blijft draaien):
  ```powershell
  Unregister-ScheduledTask -TaskName "OudWestOasis-AirbnbLaptop" -Confirm:$false
  ```
  De heartbeat veroudert binnen 3 min en de cloud neemt het vanzelf weer over.

## Aandachtspunten

- **Reactietijd:** laptop ~1 min; cloud ~5 min. Bij overgave een gat van max
  ~3 min (heartbeat-vervaltijd) — nooit dubbel, hooguit even wachten.
- **Alleen ingelogd:** de taak draait als je bent ingelogd (zo werken de
  gh-/git-credentials). Vergrendeld scherm is prima; uitgelogd niet.
- **Geheimen:** token/chat-id staan alleen in `laptop_secrets.ps1` (gitignored)
  en in GitHub Secrets. Nooit in de code of de repo.
- **Robuust:** geen internet of een git-fout → de ronde wordt overgeslagen, de
  bot crasht niet; de cloud is de altijd-aanwezige basis.
