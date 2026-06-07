# ☁️ Airbnb-bot naar de cloud (GitHub Actions)

Deze map is een **zelfstandige repo**. Hij draait je Airbnb-bot gratis op
GitHub Actions, ook als je laptop uit/dicht is. Geen 24/7-server nodig.

## Wat zit erin

```
airbnb-bot-cloud/
├─ oasis_airbnb_bot.py        # de bot (modi: weekly | poll | loop)
├─ airbnb_state.json          # quota + boekingen (wordt door de cloud bijgewerkt)
├─ requirements.txt           # requests + tzdata
├─ .gitignore                 # .env en logs worden NOOIT gecommit
└─ .github/workflows/
   ├─ weekly.yml              # maandag 09:00 Amsterdam → prijsadvies
   └─ poll.yml                # elke 30 min → commando's verwerken
```

## Hoe het werkt (architectuur)

| Onderdeel | Vroeger (lokaal) | Nu (cloud) |
|---|---|---|
| Wekelijks advies | `schedule` in 24/7-loop | `weekly.yml` op cron |
| Commando's + `fastlane` | `while True` long-poll | `poll.yml` elke 5 min |
| State (boekingen/quota) | bestand op je pc | bestand in de repo, teruggecommit door de workflow |
| Geheimen | in de code | **GitHub Secrets** |

De runners van GitHub zijn wegwerpbaar (alles weg na de run), daarom committen
de workflows `airbnb_state.json` na elke wijziging terug naar de repo.

---

## A. Repo aanmaken en pushen

De repo is lokaal al geïnitialiseerd met een eerste commit. Je hoeft 'm alleen
nog naar GitHub te duwen.

**Optie 1 — met GitHub CLI (`gh`), makkelijkst:**
```powershell
cd "C:\Users\joris\Claude\Oud-West Oasis\airbnb-bot-cloud"
gh repo create oud-west-airbnb-bot --public --source=. --remote=origin --push
```

**Optie 2 — handmatig:** maak op github.com een **lege, PUBLIC** repo aan
(naam bijv. `oud-west-airbnb-bot`, géén README aanvinken), en dan:
```powershell
cd "C:\Users\joris\Claude\Oud-West Oasis\airbnb-bot-cloud"
git remote add origin https://github.com/<jouw-username>/oud-west-airbnb-bot.git
git branch -M main
git push -u origin main
```

> **Public repo + privacy.** Public is nodig voor onbeperkte gratis minuten (de
> 5-min-poll). Wat is daarom afgeschermd:
> - 🔒 Token + chat-id → **GitHub Secrets** (niet in de code).
> - 🔒 **Gastnamen** → worden **niet** opgeslagen in de gecommitte state.
> - 🔒 Chat-id wordt **niet** in de logs geprint.
>
> Wel zichtbaar in `airbnb_state.json`: je quota-teller en de **datums/aantallen**
> van boekingen (zonder namen). Vind je ook dat te veel? Maak de repo dan
> **private** en zet in `poll.yml` de cron op `*/30` (binnen de 2000 gratis min).

---

## B. Secrets instellen (exacte namen)

In je repo op GitHub: **Settings → Secrets and variables → Actions → New
repository secret**. Maak er **twee** aan:

| Naam (exact) | Waarde |
|---|---|
| `TELEGRAM_BOT_TOKEN` | je BotFather-token |
| `TELEGRAM_CHAT_ID` | je Telegram chat-id (hetzelfde id als bij je andere bots) |

Zonder deze twee stopt de bot meteen met een nette foutmelding (geen token in
de code dus geen lek).

---

## C. Testen (per workflow een testknop)

Ga naar het tabblad **Actions** in je repo. Beide workflows hebben een
**"Run workflow"**-knop (`workflow_dispatch`).

1. **Wekelijks prijsadvies** → Run workflow → je krijgt direct het advies in
   Telegram (handmatig negeert de "alleen-maandag"-regel).
2. **Commando's pollen** → stuur eerst in Telegram **fastlane** (of `/status`),
   klik dan Run workflow → binnen ~30 s krijg je je prijsadvies terug en wordt
   de state geüpdatet. Daarna gebeurt dit vanzelf elke 5 min.

Zie je een ✅ groene vink? Dan draait alles. Daarna lopen de schema's vanzelf.

---

## D. Lokale versie uitzetten

Zodra de cloud werkt, hoef je lokaal niets meer te draaien:

- Sluit het venster `start_airbnb_bot.bat` (of stop `python oasis_airbnb_bot.py`).
- Staat hij in de opstartmap (Win+R → `shell:startup`)? Verwijder daar de
  snelkoppeling.
- **Belangrijk:** draai de bot niet tegelijk lokaal én in de cloud. Telegram
  levert elk bericht maar aan één `getUpdates`-lezer; twee pollers pikken elkaars
  commando's af. Kies dus óf lokaal óf cloud.

(De lokale map blijft gewoon staan voor `oudwest_marktdata.py` — die markttool
draai je elk kwartaal lokaal en kopieer je nieuwe `MARKT_*`-waarden in de code.)

---

## E. Aandachtspunten

**Tijdzone / DST.** Cron in GitHub is **UTC**. Amsterdam is UTC+2 (zomertijd) of
UTC+1 (wintertijd). Doel = maandag 09:00 lokaal. Daarom draait `weekly.yml` op
**07:00 én 08:00 UTC**, en het script verstuurt pas vanaf 09:00 lokale tijd en
maximaal 1× per week. Resultaat: altijd 09:00 Amsterdam, zomer én winter.

**Cron-vertraging.** Geplande workflows zijn "best effort": vooral rond het hele
uur kunnen ze 5-15 min later starten en heel soms (bij piekdrukte) overslaan. Het
wekelijkse advies vangt dit op met twee tijdstippen + de week-controle. Bij de
poll betekent het hooguit dat een commando iets later wordt beantwoord.

**Gratis minuten.** Een **public** repo heeft **onbeperkte** gratis
Actions-minuten — daarom kan de poll elke 5 min draaien (~8640 runs/maand) zonder
kosten. (Zou je de repo private maken, dan geldt 2000 min/maand en moet de poll
terug naar `*/30`.)

**60-dagen-pauze.** GitHub zet geplande workflows uit na 60 dagen zónder
repo-activiteit. Onze `weekly.yml` commit elke maandag de state → dat is
wekelijkse activiteit, dus hij blijft aan. Mocht het ooit toch pauzeren: ga naar
**Actions** en klik op **"Enable workflow"**.

**State niet handmatig bewerken** terwijl de cloud draait — de workflow is de
eigenaar van `airbnb_state.json`. Wil je iets wijzigen, doe het via de
commando's (`/quota`, `/boek`, `/annuleer`).
