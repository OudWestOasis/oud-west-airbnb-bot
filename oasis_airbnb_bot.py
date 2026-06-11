#!/usr/bin/env python3
"""
Oud-West Oasis | Airbnb prijs- & beschikbaarheidsbot  (cloud-editie)
===================================================================
Telegram-bot voor je Airbnb in Amsterdam Oud-West.

Wat hij doet:
  - Stuurt JOU elke week (maandag 09:00 Amsterdam) een prijsadvies voor de
    komende ~2 maanden.
  - Houdt rekening met drukke periodes in Amsterdam 2026 (events, feestdagen,
    vakanties) en adviseert per dag welke NETTO-prijs je in Airbnb moet zetten.
  - Toont per dag hoeveel het afwijkt van je standaardprijs en van het
    Oud-West gemiddelde (concurrentie).
  - Houdt je nachten-quota bij: max 30 nachten in 2026.

Draaimodi:
  python oasis_airbnb_bot.py weekly   # stuur het wekelijkse advies (cron-taak)
  python oasis_airbnb_bot.py poll     # eenmalig nieuwe commando's verwerken
  python oasis_airbnb_bot.py loop     # 24/7 lokaal (oud gedrag; vereist 'schedule')

Geheimen komen uit omgevingsvariabelen (GitHub Secrets):
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""

import json
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

# ============================================================
#  CONFIGURATIEBLOK  -- pas hier je eigen waarden aan (GEEN geheimen)
# ============================================================

# --- Telegram (geheimen uit omgevingsvariabelen / GitHub Secrets) ---
# Geen echte waarden in de code: lokaal via env zetten, in de cloud via Secrets.
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# --- Tijdzone ---
TIJDZONE = ZoneInfo("Europe/Amsterdam")

# --- Nachten-quota 2026 ---
JAAR = 2026
NACHTEN_QUOTA = 30          # max. te verhuren nachten dit jaar
REEDS_GEBOEKT = 3           # nachten die al verbruikt waren voor de bot ging tellen

# --- Basisprijzen (NETTO: het bedrag dat JIJ in de Airbnb-app instelt) ---
PRIJS_DOORDEWEEKS = 280     # zondag t/m donderdag nacht
PRIJS_WEEKEND = 295         # vrijdag- en zaterdagnacht
WEEKEND_DAGEN = (4, 5)      # Python weekday(): ma=0 ... vr=4, za=5

# Vakantieperiode: vaste lage prijs (je bent dan zelf op vakantie).
VAKANTIE_START = date(2026, 6, 19)
VAKANTIE_EIND = date(2026, 7, 12)   # t/m deze datum
PRIJS_VAKANTIE = 270

# --- Markt-referentie Oud-West (ECHTE DATA) ---
# Bron: Inside Airbnb, snapshot 11-09-2025. 435 vergelijkbare hele woningen in
# "De Baarsjes - Oud-West" met 1 slaapkamer / 2 gasten.
#   Mediaan EUR213 · Gemiddeld EUR235 · 75e perc. EUR270 · 90e perc. EUR316
MARKT_DOORDEWEEKS = 225
MARKT_WEEKEND = 245
MARKT_EVENT_FACTOR = 0.9
SEIZOENSINDEX = {
    1: 0.82, 2: 0.84, 3: 0.92, 4: 1.08, 5: 1.08, 6: 1.06,
    7: 1.12, 8: 1.12, 9: 1.04, 10: 1.00, 11: 0.88, 12: 0.95,
}

# --- Wekelijks bericht ---
VERSTUUR_DAG = "maandag"    # welke dag de wekelijkse update komt
VERSTUUR_TIJD = "09:00"     # tijdstip (24u-notatie, lokale tijd)
HORIZON_WEKEN = 8           # ~2 maanden vooruit kijken
AFRONDEN_OP = 5             # prijzen afronden op veelvoud van EUR 5

# --- Bestanden ---
LOG_FILE = "oasis_airbnb_bot.log"
STATE_FILE = "airbnb_state.json"

# ============================================================
#  DRUKKE PERIODES AMSTERDAM 2026
#  (start, eind, opslag-fractie, label)  -- opslag boven je basisprijs.
#  Bij overlap wint de hoogste opslag.
# ============================================================
DRUKKE_PERIODES = [
    ("2026-03-19", "2026-05-10", 0.06, "Tulpenseizoen / Keukenhof"),
    ("2026-04-03", "2026-04-06", 0.12, "Paasweekend"),
    ("2026-04-24", "2026-04-27", 0.30, "Koningsnacht & Koningsdag"),
    ("2026-04-25", "2026-05-03", 0.12, "Meivakantie"),
    ("2026-05-04", "2026-05-05", 0.06, "Bevrijdingsdag"),
    ("2026-05-14", "2026-05-17", 0.10, "Hemelvaart-weekend"),
    ("2026-05-23", "2026-05-25", 0.10, "Pinksteren"),
    ("2026-07-04", "2026-08-16", 0.10, "Zomervakantie (regio Noord)"),
    ("2026-07-25", "2026-08-08", 0.15, "World Pride Amsterdam"),
    ("2026-07-31", "2026-08-01", 0.30, "Canal Parade (Pride-hoogtepunt)"),
    ("2026-08-21", "2026-08-23", 0.28, "Dutch GP Zandvoort (laatste editie)"),
    ("2026-10-17", "2026-10-25", 0.12, "Herfstvakantie"),
    ("2026-10-21", "2026-10-25", 0.28, "Amsterdam Dance Event (ADE)"),
    ("2026-12-19", "2027-01-03", 0.10, "Kerstvakantie"),
    ("2026-12-24", "2026-12-26", 0.15, "Kerst"),
    ("2026-12-29", "2027-01-01", 0.30, "Oud & Nieuw"),
]
_DRUK = [
    (date.fromisoformat(s), date.fromisoformat(e), u, l)
    for s, e, u, l in DRUKKE_PERIODES
]

# ============================================================
#  LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("oasis-airbnb")

# Nederlandse datumnamen (locale-onafhankelijk)
DAGEN = ["ma", "di", "wo", "do", "vr", "za", "zo"]
MAANDEN = ["", "jan", "feb", "mrt", "apr", "mei", "jun",
           "jul", "aug", "sep", "okt", "nov", "dec"]


def fmt_dag(d: date) -> str:
    """Bijv. 'za 1 aug'."""
    return f"{DAGEN[d.weekday()]} {d.day} {MAANDEN[d.month]}"


def vandaag_lokaal() -> date:
    """Datum in Amsterdamse tijd (runner draait op UTC)."""
    return datetime.now(TIJDZONE).date()


# ============================================================
#  STATE (op schijf)
# ============================================================
def _default_state() -> dict:
    return {
        "reeds_geboekt": REEDS_GEBOEKT,
        "boekingen": [],          # [{id, checkin, checkout, nachten, naam}]
        "volgende_id": 1,
        "update_offset": 0,       # voor Telegram getUpdates
        "laatste_week_run": "",   # ISO-week waarin het advies al verstuurd is
    }


def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        st = _default_state()
        save_state(st)
        return st
    try:
        with open(STATE_FILE, encoding="utf-8") as fh:
            st = json.load(fh)
        for k, v in _default_state().items():
            st.setdefault(k, v)
        return st
    except (OSError, json.JSONDecodeError) as exc:
        log.error("Kon state niet lezen (%s) — start met lege state.", exc)
        return _default_state()


def save_state(st: dict) -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as fh:
            json.dump(st, fh, indent=2, ensure_ascii=False)
    except OSError as exc:
        log.error("Kon state niet schrijven: %s", exc)


def gebruikte_nachten(st: dict) -> int:
    return st["reeds_geboekt"] + sum(b["nachten"] for b in st["boekingen"])


def resterende_nachten(st: dict) -> int:
    return NACHTEN_QUOTA - gebruikte_nachten(st)


# ============================================================
#  PRIJSLOGICA
# ============================================================
def afronden(x: float) -> int:
    return int(round(x / AFRONDEN_OP) * AFRONDEN_OP)


def is_weekend(d: date) -> bool:
    return d.weekday() in WEEKEND_DAGEN


def in_vakantie(d: date) -> bool:
    return VAKANTIE_START <= d <= VAKANTIE_EIND


def basisprijs(d: date) -> int:
    if in_vakantie(d):
        return PRIJS_VAKANTIE
    return PRIJS_WEEKEND if is_weekend(d) else PRIJS_DOORDEWEEKS


def drukte_voor(d: date):
    """Geeft (opslag, label) van de drukste period op deze dag, anders (0, None)."""
    beste = (0.0, None)
    for s, e, u, l in _DRUK:
        if s <= d <= e and u > beste[0]:
            beste = (u, l)
    return beste


def marktgemiddelde(d: date) -> int:
    basis = MARKT_WEEKEND if is_weekend(d) else MARKT_DOORDEWEEKS
    opslag, _ = drukte_voor(d)
    return afronden(basis * SEIZOENSINDEX[d.month] * (1 + opslag * MARKT_EVENT_FACTOR))


def advies_voor(d: date) -> dict:
    """Volledig prijsadvies voor één nacht."""
    basis = basisprijs(d)
    opslag, label = drukte_voor(d)
    aanbevolen = afronden(basis * (1 + opslag)) if opslag else basis
    markt = marktgemiddelde(d)
    return {
        "datum": d,
        "basis": basis,
        "opslag": opslag,
        "label": label,
        "aanbevolen": aanbevolen,
        "vs_basis_pct": round((aanbevolen / basis - 1) * 100),
        "markt": markt,
        "vs_markt_pct": round((aanbevolen / markt - 1) * 100),
        "weekend": is_weekend(d),
        "vakantie": in_vakantie(d),
        "bijzonder": opslag > 0,
    }


def komende_drukke_periodes(vanaf: date | None = None) -> list:
    """Alle drukke periodes vanaf vandaag, gesorteerd op hoogste opslag eerst."""
    vanaf = vanaf or vandaag_lokaal()
    items = []
    for s, e, u, l in _DRUK:
        if e >= vanaf:
            items.append({
                "start": max(s, vanaf), "eind": e, "opslag": u, "label": l,
                "prijs_dw": afronden(PRIJS_DOORDEWEEKS * (1 + u)),
                "prijs_wk": afronden(PRIJS_WEEKEND * (1 + u)),
            })
    items.sort(key=lambda x: (-x["opslag"], x["start"]))
    return items


def format_topdagen(items: list, n: int = 6) -> list:
    """Maakt nette regels van de beste verkoopperiodes."""
    regels = []
    for it in items[:n]:
        periode = (fmt_dag(it["start"]) if it["start"] == it["eind"]
                   else f"{fmt_dag(it['start'])}–{fmt_dag(it['eind'])}")
        regels.append(
            f"• {periode} — {it['label']}: "
            f"€{it['prijs_dw']} dw / €{it['prijs_wk']} wk (+{int(it['opslag']*100)}%)"
        )
    return regels


# ============================================================
#  WEKELIJKS PRIJSADVIES (bericht opbouwen)
# ============================================================
def bouw_weekbericht(vandaag: date | None = None) -> str:
    vandaag = vandaag or vandaag_lokaal()
    st = load_state()

    maandag = vandaag - timedelta(days=vandaag.weekday())
    over = resterende_nachten(st)
    gebruikt = gebruikte_nachten(st)

    regels = []
    regels.append("🌴 *Oud-West Oasis | Prijsadvies*")
    regels.append(f"🗓️ {vandaag:%d-%m-%Y} — komende {HORIZON_WEKEN} weken\n")

    regels.append("*📊 Beschikbaarheid 2026*")
    regels.append(f"Quota: {NACHTEN_QUOTA} nachten · gebruikt: {gebruikt} · *nog vrij: {over}*")
    if over > 0:
        regels.append(f"👉 Zet je Airbnb-beschikbaarheid op *{over} nachten*.")
    elif over == 0:
        regels.append("⚠️ Je zit op je maximum: zet je beschikbaarheid op *0 nachten*.")
    else:
        regels.append(f"🚨 Je zit *{-over} nachten boven* je quota! Controleer je boekingen.")
    regels.append("")

    top = komende_drukke_periodes(vandaag)
    if top and over > 0:
        regels.append("*🎯 Beste verkoopdagen 2026 — zet hier je nachten open*")
        regels.extend(format_topdagen(top, 6))
        regels.append("_Premium-strategie: hier boekt een hoge prijs het makkelijkst._")
        regels.append("")

    regels.append("*💶 Je standaardprijzen (netto)*")
    regels.append(f"Doordeweeks €{PRIJS_DOORDEWEEKS} · Weekend (vr/za) €{PRIJS_WEEKEND}")
    regels.append(
        f"Vakantie {fmt_dag(VAKANTIE_START)}–{fmt_dag(VAKANTIE_EIND)}: €{PRIJS_VAKANTIE} vast"
    )
    regels.append("")

    alle_bijzonder = []
    for w in range(HORIZON_WEKEN):
        wk_start = maandag + timedelta(days=7 * w)
        wk_eind = wk_start + timedelta(days=6)
        dagen = [wk_start + timedelta(days=i) for i in range(7)]

        regels.append(f"*Week {w + 1} · {fmt_dag(wk_start)} – {fmt_dag(wk_eind)}*")

        mkt_dw = marktgemiddelde(wk_start + timedelta(days=2))
        mkt_wk = marktgemiddelde(wk_start + timedelta(days=4))
        regels.append(f"• Standaard: €{PRIJS_DOORDEWEEKS} dw / €{PRIJS_WEEKEND} wk "
                      f"— Oud-West gem. ~€{mkt_dw}/{mkt_wk}")

        if any(in_vakantie(d) for d in dagen):
            regels.append(f"• 🏖️ Vakantieprijs €{PRIJS_VAKANTIE} actief — je staat hier bewust laag")

        for d in dagen:
            if d < vandaag:
                continue
            a = advies_voor(d)
            if a["bijzonder"]:
                alle_bijzonder.append(a)
                regels.append(
                    f"• ⭐ {fmt_dag(d)} — {a['label']}: zet *€{a['aanbevolen']}* "
                    f"({a['vs_basis_pct']:+d}% vs standaard, {a['vs_markt_pct']:+d}% vs markt)"
                )
        regels.append("")

    if alle_bijzonder:
        regels.append("*📌 Alle prijswijzigingen op een rij*")
        for a in alle_bijzonder:
            regels.append(
                f"• {fmt_dag(a['datum'])}: €{a['basis']} → *€{a['aanbevolen']}* "
                f"({a['vs_basis_pct']:+d}%) — {a['label']}"
            )
    else:
        regels.append("Geen bijzondere drukte komende periode — houd je standaardprijzen aan.")

    regels.append("")
    regels.append("_Markt = echte Inside Airbnb-data (Oud-West, 1 slpk/2 gasten)._")
    return "\n".join(regels)


def bouw_fastlane(vandaag: date | None = None) -> str:
    """Kort, overzichtelijk prijsoverzicht: nachten vrij + prijzen komende ~2 mnd."""
    vandaag = vandaag or vandaag_lokaal()
    st = load_state()
    over = resterende_nachten(st)
    gebruikt = gebruikte_nachten(st)
    eind = vandaag + timedelta(weeks=HORIZON_WEKEN)

    r = []
    r.append("🏁 *Fast Lane — prijsoverzicht*")
    r.append(f"🗓️ {vandaag:%d-%m-%Y}\n")
    r.append(f"📊 *Nog {over} van {NACHTEN_QUOTA} nachten vrij* ({gebruikt} gebruikt).")
    r.append(f"👉 Zet je Airbnb-beschikbaarheid op *{max(over, 0)} nachten*.")
    r.append("")
    r.append(f"💶 *Prijs per nacht (netto) — komende {HORIZON_WEKEN} weken:*")
    r.append(f"• Doordeweeks *€{PRIJS_DOORDEWEEKS}* · weekend vr/za *€{PRIJS_WEEKEND}*")
    if VAKANTIE_START <= eind and VAKANTIE_EIND >= vandaag:
        r.append(f"• Vakantie {fmt_dag(VAKANTIE_START)}–{fmt_dag(VAKANTIE_EIND)}: "
                 f"*€{PRIJS_VAKANTIE}* (je bent zelf weg)")

    # Drukke periodes binnen de horizon, op datum (overzichtelijk gegroepeerd).
    periodes = [p for p in komende_drukke_periodes(vandaag) if p["start"] <= eind]
    periodes.sort(key=lambda p: p["start"])
    if periodes:
        r.append("")
        r.append("⭐ *Drukke dagen — zet dan hoger:*")
        for p in periodes:
            per = (fmt_dag(p["start"]) if p["start"] == p["eind"]
                   else f"{fmt_dag(p['start'])}–{fmt_dag(p['eind'])}")
            r.append(f"• {per} — {p['label']}: €{p['prijs_dw']}/€{p['prijs_wk']} "
                     f"(+{int(p['opslag']*100)}%)")
    else:
        r.append("")
        r.append("Geen bijzondere drukte de komende 2 maanden — houd de standaardprijs aan.")

    r.append("\n_Volledig advies? Stuur /advies._")
    return "\n".join(r)


# ============================================================
#  TELEGRAM API
# ============================================================
def _api(method: str) -> str:
    return f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"


def send_telegram(message: str, chat_id: str | None = None) -> bool:
    """Verstuurt een (eventueel lang) bericht. Splitst automatisch > 4000 tekens."""
    chat_id = chat_id or TELEGRAM_CHAT_ID
    for chunk in _split_message(message):
        try:
            resp = requests.post(
                _api("sendMessage"),
                data={"chat_id": chat_id, "text": chunk, "parse_mode": "Markdown"},
                timeout=20,
            )
            if resp.status_code == 403:
                log.error("403 van Telegram: de ontvanger heeft de bot nog niet "
                          "gestart (open de bot en druk op START).")
                return False
            resp.raise_for_status()
        except requests.exceptions.RequestException as exc:
            log.error("Versturen mislukt: %s", exc)
            return False
    log.info("Bericht verstuurd.")   # chat-id niet loggen (public repo = openbare logs)
    return True


def _split_message(message: str, limit: int = 4000) -> list:
    """Knipt netjes op lege regels zodat Markdown heel blijft."""
    if len(message) <= limit:
        return [message]
    delen, huidig = [], ""
    for blok in message.split("\n\n"):
        if len(huidig) + len(blok) + 2 > limit:
            if huidig:
                delen.append(huidig.rstrip())
            huidig = blok + "\n\n"
        else:
            huidig += blok + "\n\n"
    if huidig.strip():
        delen.append(huidig.rstrip())
    return delen


def get_updates(offset: int, timeout: int = 50) -> list:
    """Haalt nieuwe berichten/commando's op. timeout=0 = direct teruggeven."""
    try:
        resp = requests.get(
            _api("getUpdates"),
            params={"offset": offset, "timeout": timeout},
            timeout=timeout + 10,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("result", []) if data.get("ok") else []
    except requests.exceptions.RequestException as exc:
        log.warning("getUpdates fout: %s", exc)
        return []


# ============================================================
#  COMMANDO'S
# ============================================================
HELP_TEKST = (
    "🌴 *Oud-West Oasis | Airbnb-bot*\n\n"
    "*Commando's:*\n"
    "/advies — stuur nu het prijsadvies (komende 2 maanden)\n"
    "/topdagen — beste verkoopdagen rest van 2026 (waar je nachten openzetten)\n"
    "/status — quota & komende boekingen\n"
    "/boek JJJJ-MM-DD JJJJ-MM-DD [naam] — boeking toevoegen\n"
    "    bijv. `/boek 2026-07-20 2026-07-24 Jan`\n"
    "/boekingen — lijst van boekingen\n"
    "/annuleer ID — boeking verwijderen (ID uit /boekingen)\n"
    "/quota N — aantal reeds-verbruikte nachten bijstellen (nu "
    f"{REEDS_GEBOEKT})\n"
    "/prijs JJJJ-MM-DD — prijsadvies voor één specifieke datum\n"
    "/help — deze lijst\n\n"
    "⚡ Snel: stuur *fastlane* (hoofd/klein maakt niet uit) → kort overzicht: "
    "nachten vrij + prijzen 2 maanden.\n"
    f"Het wekelijkse advies komt automatisch elke {VERSTUUR_DAG} om {VERSTUUR_TIJD}.\n"
    "_(In de cloud worden commando's elke ~5 min opgehaald.)_"
)


def cmd_status(st, chat_id, args):
    over = resterende_nachten(st)
    gebruikt = gebruikte_nachten(st)
    regels = [
        "*📊 Status*",
        f"Quota {JAAR}: {NACHTEN_QUOTA} nachten",
        f"Gebruikt: {gebruikt} (waarvan {st['reeds_geboekt']} reeds geboekt + "
        f"{gebruikt - st['reeds_geboekt']} via bot)",
        f"*Nog vrij: {over} nachten*",
        f"👉 Zet je Airbnb-beschikbaarheid op {max(over, 0)} nachten.",
    ]
    if st["boekingen"]:
        regels.append("\n*Komende boekingen:*")
        for b in sorted(st["boekingen"], key=lambda x: x["checkin"]):
            ci = date.fromisoformat(b["checkin"])
            co = date.fromisoformat(b["checkout"])
            naam = f" — {b['naam']}" if b.get("naam") else ""
            regels.append(f"  #{b['id']}: {fmt_dag(ci)} → {fmt_dag(co)} "
                          f"({b['nachten']} nachten){naam}")
    send_telegram("\n".join(regels), chat_id)


def cmd_boek(st, chat_id, args):
    if len(args) < 2:
        send_telegram("Gebruik: `/boek JJJJ-MM-DD JJJJ-MM-DD [naam]`\n"
                      "Bijv. `/boek 2026-07-20 2026-07-24 Jan`", chat_id)
        return
    try:
        ci = date.fromisoformat(args[0])
        co = date.fromisoformat(args[1])
    except ValueError:
        send_telegram("Datum niet herkend. Gebruik formaat JJJJ-MM-DD.", chat_id)
        return
    if co <= ci:
        send_telegram("Check-out moet ná check-in liggen.", chat_id)
        return
    # Privacy: deze bot draait in een PUBLIC repo, dus we bewaren GEEN gastnamen
    # in de (gecommitte) state. Alleen datums en aantal nachten.
    naam = ""
    nachten = (co - ci).days

    b = {
        "id": st["volgende_id"],
        "checkin": ci.isoformat(),
        "checkout": co.isoformat(),
        "nachten": nachten,
        "naam": naam,
    }
    st["boekingen"].append(b)
    st["volgende_id"] += 1
    save_state(st)

    over = resterende_nachten(st)
    regels = [
        f"✅ Boeking #{b['id']} toegevoegd: {fmt_dag(ci)} → {fmt_dag(co)} "
        f"(*{nachten} nachten*){' — ' + naam if naam else ''}",
        f"*Nog vrij: {over} nachten* van je {NACHTEN_QUOTA}.",
        f"👉 Zet je Airbnb-beschikbaarheid nu op {max(over, 0)} nachten.",
    ]
    if over < 0:
        regels.append(f"🚨 Let op: je zit {-over} nachten boven je quota!")
    elif over == 0:
        regels.append("⚠️ Dit was je laatste beschikbare nacht-budget.")
    send_telegram("\n".join(regels), chat_id)


def cmd_boekingen(st, chat_id, args):
    if not st["boekingen"]:
        send_telegram("Nog geen boekingen geregistreerd.", chat_id)
        return
    regels = ["*📒 Boekingen:*"]
    for b in sorted(st["boekingen"], key=lambda x: x["checkin"]):
        ci = date.fromisoformat(b["checkin"])
        co = date.fromisoformat(b["checkout"])
        naam = f" — {b['naam']}" if b.get("naam") else ""
        regels.append(f"  #{b['id']}: {fmt_dag(ci)} → {fmt_dag(co)} "
                      f"({b['nachten']} nachten){naam}")
    regels.append(f"\nTotaal via bot: {sum(b['nachten'] for b in st['boekingen'])} nachten.")
    send_telegram("\n".join(regels), chat_id)


def cmd_annuleer(st, chat_id, args):
    if not args or not args[0].isdigit():
        send_telegram("Gebruik: `/annuleer ID` (ID uit /boekingen).", chat_id)
        return
    bid = int(args[0])
    voor = len(st["boekingen"])
    st["boekingen"] = [b for b in st["boekingen"] if b["id"] != bid]
    if len(st["boekingen"]) == voor:
        send_telegram(f"Geen boeking met ID #{bid} gevonden.", chat_id)
        return
    save_state(st)
    over = resterende_nachten(st)
    send_telegram(f"🗑️ Boeking #{bid} geannuleerd.\n*Nog vrij: {over} nachten.*\n"
                  f"👉 Zet je beschikbaarheid op {max(over, 0)} nachten.", chat_id)


def cmd_quota(st, chat_id, args):
    if not args or not args[0].isdigit():
        send_telegram(f"Gebruik: `/quota N` — aantal reeds-verbruikte nachten "
                      f"(nu {st['reeds_geboekt']}).", chat_id)
        return
    st["reeds_geboekt"] = int(args[0])
    save_state(st)
    over = resterende_nachten(st)
    send_telegram(f"✅ Reeds-verbruikt op {st['reeds_geboekt']} gezet. "
                  f"*Nog vrij: {over} nachten.*", chat_id)


def cmd_prijs(st, chat_id, args):
    if not args:
        send_telegram("Gebruik: `/prijs JJJJ-MM-DD`.", chat_id)
        return
    try:
        d = date.fromisoformat(args[0])
    except ValueError:
        send_telegram("Datum niet herkend. Gebruik JJJJ-MM-DD.", chat_id)
        return
    a = advies_voor(d)
    soort = "weekend" if a["weekend"] else "doordeweeks"
    if a["vakantie"]:
        soort = "vakantieperiode"
    regels = [
        f"*💶 Prijsadvies {fmt_dag(d)} {d.year}*",
        f"Soort: {soort}",
        f"Aanbevolen netto-prijs: *€{a['aanbevolen']}*",
    ]
    if a["bijzonder"]:
        regels.append(f"Reden: {a['label']} ({a['vs_basis_pct']:+d}% boven je standaard €{a['basis']})")
    else:
        regels.append(f"Standaardprijs (geen bijzondere drukte): €{a['basis']}")
    regels.append(f"Oud-West gemiddeld: ~€{a['markt']} ({a['vs_markt_pct']:+d}% verschil)")
    send_telegram("\n".join(regels), chat_id)


def cmd_advies(st, chat_id, args):
    send_telegram(bouw_weekbericht(), chat_id)


def cmd_topdagen(st, chat_id, args):
    top = komende_drukke_periodes()
    over = resterende_nachten(st)
    regels = ["*🎯 Beste verkoopdagen — rest van 2026*",
              f"Je hebt nog *{over} nachten* te verkopen. Zet je beschikbaarheid "
              "bij voorkeur open op deze drukke periodes:\n"]
    regels.extend(format_topdagen(top, 10))
    send_telegram("\n".join(regels), chat_id)


def cmd_start(st, chat_id, args):
    send_telegram(
        "🌴 Welkom bij je *Oud-West Oasis* Airbnb-assistent!\n\n"
        "Ik stuur je elke week een prijsadvies en houd je nachten-quota bij.\n\n"
        + HELP_TEKST, chat_id)


def cmd_help(st, chat_id, args):
    send_telegram(HELP_TEKST, chat_id)


COMMANDOS = {
    "start": cmd_start,
    "help": cmd_help,
    "advies": cmd_advies,
    "topdagen": cmd_topdagen,
    "status": cmd_status,
    "boek": cmd_boek,
    "boekingen": cmd_boekingen,
    "annuleer": cmd_annuleer,
    "quota": cmd_quota,
    "prijs": cmd_prijs,
}


def verwerk_update(update: dict, st: dict) -> None:
    msg = update.get("message") or update.get("edited_message")
    if not msg or "text" not in msg:
        return
    chat_id = str(msg["chat"]["id"])
    tekst = msg["text"].strip()
    low = tekst.lower()
    # Trefwoord "fastlane": hoofd-/kleine letters, met/zonder spatie of streepje,
    # en wat veelvoorkomende verschrijvingen -> kort prijsoverzicht (geen / nodig).
    if any(k in low for k in ("fastlane", "fast lane", "fast-lane",
                              "fastline", "fast line", "faslane")):
        send_telegram(bouw_fastlane(), chat_id)
        return
    if not tekst.startswith("/"):
        send_telegram("Typ /help voor de commando's — of stuur *fastlane* "
                      "voor een kort prijsoverzicht.", chat_id)
        return
    delen = tekst.split()
    cmd = delen[0][1:].split("@")[0].lower()   # /boek@BotNaam -> boek
    args = delen[1:]
    handler = COMMANDOS.get(cmd)
    if handler:
        try:
            handler(st, chat_id, args)
        except Exception as exc:  # noqa: BLE001 - bot mag niet crashen
            log.error("Fout bij commando /%s: %s", cmd, exc)
            send_telegram(f"Er ging iets mis bij /{cmd}.", chat_id)
    else:
        send_telegram(f"Onbekend commando /{cmd}. Typ /help.", chat_id)


# ============================================================
#  CLOUD-ENTRYPOINTS
# ============================================================
def _require_secrets() -> None:
    ontbreekt = [n for n, v in (("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
                                ("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID)) if not v]
    if ontbreekt:
        log.error("Ontbrekende secrets: %s. Zet ze als omgevingsvariabele / "
                  "GitHub Secret.", ", ".join(ontbreekt))
        raise SystemExit(1)


def run_weekly_once() -> bool:
    """Stuur het wekelijkse advies. Bij 'schedule': alleen ma vanaf 09:00 lokaal,
    1x per ISO-week (DST-proof). Bij handmatig/dispatch/lokaal: altijd sturen."""
    now = datetime.now(TIJDZONE)
    scheduled = os.getenv("GITHUB_EVENT_NAME", "") == "schedule"
    week_id = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"
    st = load_state()

    if scheduled:
        if now.weekday() != 0 or now.hour < 9:
            log.info("Weekly: nog niet maandag 09:00 Amsterdam (nu %s) — overslaan.",
                     now.strftime("%a %H:%M"))
            return False
        if st.get("laatste_week_run") == week_id:
            log.info("Weekly: deze week (%s) al verstuurd — overslaan.", week_id)
            return False

    if send_telegram(bouw_weekbericht(now.date())):
        st["laatste_week_run"] = week_id
        save_state(st)
        log.info("Weekly: advies verstuurd (%s).", week_id)
        return True
    return False


def run_poll_once() -> bool:
    """Haal in één keer alle openstaande commando's op, verwerk en bewaar state."""
    st = load_state()
    offset = st.get("update_offset", 0)
    updates = get_updates(offset, timeout=0)
    if not updates:
        log.info("Poll: geen nieuwe berichten.")
        return False
    for upd in updates:
        offset = upd["update_id"] + 1
        verwerk_update(upd, st)
    st = load_state()           # handlers kunnen tussentijds hebben opgeslagen
    st["update_offset"] = offset
    save_state(st)
    log.info("Poll: %d update(s) verwerkt.", len(updates))
    return True


def run_loop() -> None:
    """24/7 lokaal draaien (oud gedrag). Vereist 'pip install schedule'."""
    import schedule

    def wekelijkse_check():
        now = datetime.now(TIJDZONE)
        if now.weekday() != 0:
            return
        week_id = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"
        st = load_state()
        if st.get("laatste_week_run") == week_id:
            return
        if send_telegram(bouw_weekbericht(now.date())):
            st["laatste_week_run"] = week_id
            save_state(st)

    log.info("🌴 Airbnb-bot gestart (lokale 24/7-modus).")
    schedule.every().day.at(VERSTUUR_TIJD).do(wekelijkse_check)
    offset = load_state().get("update_offset", 0)
    while True:
        try:
            updates = get_updates(offset, timeout=50)
            if updates:
                st = load_state()
                for upd in updates:
                    offset = upd["update_id"] + 1
                    verwerk_update(upd, st)
                st = load_state()
                st["update_offset"] = offset
                save_state(st)
            schedule.run_pending()
        except KeyboardInterrupt:
            log.info("Bot gestopt. Tot ziens! 🌴")
            break
        except Exception as exc:  # noqa: BLE001
            log.error("Onverwachte fout in hoofdloop: %s", exc)
            time.sleep(10)


# ============================================================
#  OVERNAME LAPTOP <-> CLOUD  (heartbeat + stand-by)
# ============================================================
def _laptop_actief() -> bool:
    """True als de laptop-heartbeat vers is (< 3 min). Robuust: bij ontbreken of
    een onleesbare waarde -> False (dan draait de cloud gewoon, dat is de basis)."""
    hb = os.getenv("LAPTOP_HEARTBEAT", "").strip()
    if not hb:
        return False
    try:
        ts = datetime.fromisoformat(hb.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - ts) < timedelta(minutes=3)


def run_weekly_if_due() -> bool:
    """Stuurt het wekelijkse advies als het maandag >= 09:00 lokaal is en deze
    ISO-week nog niet verstuurd is. Idempotent en locatie-onafhankelijk."""
    now = datetime.now(TIJDZONE)
    if now.weekday() != 0 or now.hour < 9:
        return False
    week_id = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"
    st = load_state()
    if st.get("laatste_week_run") == week_id:
        return False
    if send_telegram(bouw_weekbericht(now.date())):
        st["laatste_week_run"] = week_id
        save_state(st)
        log.info("Weekly: advies verstuurd (%s).", week_id)
        return True
    return False


def run_tick() -> None:
    """Eén ronde voor zowel laptop als cloud: commando's + wekelijkse check.
    De CLOUD slaat de ronde volledig over als de laptop actief is (heartbeat vers);
    de LAPTOP draait altijd. Berichten-inhoud verandert niet — alleen WIE stuurt."""
    location = os.getenv("RUN_LOCATION", "cloud")
    if location == "cloud" and _laptop_actief():
        log.info("laptop actief — cloud staat stand-by (ronde overgeslagen).")
        return
    run_poll_once()
    run_weekly_if_due()


def main() -> None:
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else "loop"
    _require_secrets()
    if mode == "weekly":
        run_weekly_once()
    elif mode == "poll":
        run_poll_once()
    elif mode == "tick":
        run_tick()
    elif mode == "loop":
        run_loop()
    else:
        log.error("Onbekende modus '%s'. Gebruik: tick | weekly | poll | loop", mode)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
