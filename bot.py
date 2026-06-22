"""
🎮 GamingFlip Bot v2 — Alertes temps réel achat-revente gaming
Vinted + Leboncoin | Annonces < 10 min | Conseil négociation
"""

import os
import asyncio
import logging
import json
import re
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import aiohttp
from bs4 import BeautifulSoup
from telegram import Bot
from telegram.error import TelegramError

# ═══════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
EBAY_APP_ID      = os.getenv("EBAY_APP_ID", "")

MARGE_MIN_PCT    = 50       # % marge nette minimum pour alerter
MAX_AGE_MINUTES  = 10       # Ignorer les annonces de plus de 10 min
SCRAPE_INTERVAL  = 240      # Cycle toutes les 4 min (< 10 min de fraîcheur)
TZ               = ZoneInfo("Europe/Paris")

# ═══════════════════════════════════════════════════════════
# MOTS-CLÉS — EXHAUSTIF
# ═══════════════════════════════════════════════════════════
KEYWORDS_VINTED = [
    # ── Nintendo Switch ──────────────────────────────────
    "zelda breath wild switch",
    "zelda tears kingdom switch",
    "mario kart 8 switch",
    "super mario odyssey switch",
    "super mario bros wonder switch",
    "pokemon ecarlate switch",
    "pokemon violet switch",
    "pokemon epee switch",
    "pokemon bouclier switch",
    "pokemon arceus switch",
    "animal crossing switch",
    "splatoon 3 switch",
    "kirby switch",
    "metroid switch",
    "xenoblade switch",
    "fire emblem switch",
    "astral chain switch",
    "bayonetta switch",
    "luigi mansion switch",
    "donkey kong switch",
    "smash bros switch",
    "mario party switch",
    "mario 3d world switch",
    "mario rabbids switch",
    "minecraft switch",
    "stardew valley switch",
    "hollow knight switch",
    "lot jeux switch",
    "console switch occasion",
    "nintendo switch lite occasion",
    # ── PS4 ──────────────────────────────────────────────
    "the last of us ps4",
    "god of war ps4",
    "spider man ps4",
    "red dead redemption 2 ps4",
    "ghost of tsushima ps4",
    "horizon zero dawn ps4",
    "uncharted 4 ps4",
    "bloodborne ps4",
    "dark souls ps4",
    "sekiro ps4",
    "elden ring ps4",
    "persona 5 ps4",
    "detroit become human ps4",
    "death stranding ps4",
    "days gone ps4",
    "resident evil 7 ps4",
    "resident evil village ps4",
    "cyberpunk ps4",
    "witcher 3 ps4",
    "batman arkham ps4",
    "far cry ps4",
    "assassin creed ps4",
    "call of duty ps4",
    "fifa ps4",
    "lot jeux ps4",
    "manette ps4 dualshock",
    "manette ps4 occasion",
    # ── Xbox ─────────────────────────────────────────────
    "manette xbox one occasion",
    "manette xbox series occasion",
    "lot jeux xbox one",
    # ── Retrogaming GBA / DS ─────────────────────────────
    "game boy advance console",
    "game boy advance sp",
    "game boy color console",
    "game boy pocket",
    "gameboy advance jeu",
    "pokemon gameboy",
    "zelda gameboy",
    "mario gameboy",
    "nintendo ds console",
    "nintendo ds lite",
    "nintendo dsi",
    "nintendo 3ds console",
    "nintendo 3ds xl",
    "new 3ds xl",
    "lot jeux ds",
    "lot jeux 3ds",
    # ── PSP / PSVita ─────────────────────────────────────
    "psp playstation portable console",
    "psp 3000 console",
    "ps vita console",
    "playstation vita",
    "lot jeux psp",
    # ── PS1 / PS2 / N64 ──────────────────────────────────
    "console playstation 1",
    "console ps1 sony",
    "console ps2 sony",
    "nintendo 64 console",
    "n64 console",
    "super nintendo console",
    "snes console",
    "megadrive console",
    "lot jeux ps1",
    "lot jeux ps2",
]

KEYWORDS_LBC = [
    # Switch
    "zelda switch", "mario kart switch", "pokemon switch",
    "mario odyssey switch", "animal crossing switch",
    "lot jeux switch", "console switch",
    # PS4
    "the last of us ps4", "god of war ps4", "spider-man ps4",
    "red dead redemption ps4", "ghost of tsushima ps4",
    "horizon zero dawn ps4", "lot jeux ps4", "manette ps4",
    # Retrogaming
    "game boy advance", "game boy color", "gameboy advance",
    "nintendo ds", "nintendo 3ds", "psp console",
    "playstation 1", "playstation 2", "nintendo 64",
    "super nintendo", "megadrive",
    # Lots
    "lot jeux video", "collection jeux video",
]

# ═══════════════════════════════════════════════════════════
# COTES DE RÉFÉRENCE (eBay FR objets vendus — Juin 2026)
# Format : "mots clés" -> {min, max} en €
# ═══════════════════════════════════════════════════════════
COTES = {
    # Switch — Jeux
    "zelda breath":          {"min": 28, "max": 38},
    "zelda tears":           {"min": 35, "max": 48},
    "mario kart 8":          {"min": 28, "max": 38},
    "mario odyssey":         {"min": 22, "max": 32},
    "mario bros wonder":     {"min": 32, "max": 42},
    "pokemon ecarlate":      {"min": 28, "max": 38},
    "pokemon violet":        {"min": 28, "max": 38},
    "pokemon epee":          {"min": 22, "max": 32},
    "pokemon bouclier":      {"min": 22, "max": 32},
    "pokemon arceus":        {"min": 28, "max": 38},
    "animal crossing":       {"min": 25, "max": 35},
    "splatoon 3":            {"min": 25, "max": 35},
    "smash bros":            {"min": 28, "max": 38},
    "mario party":           {"min": 28, "max": 38},
    "mario 3d world":        {"min": 28, "max": 38},
    "luigi mansion":         {"min": 28, "max": 38},
    "xenoblade":             {"min": 30, "max": 45},
    "fire emblem":           {"min": 30, "max": 45},
    "metroid":               {"min": 25, "max": 38},
    "bayonetta":             {"min": 22, "max": 32},
    "minecraft switch":      {"min": 28, "max": 38},
    # Switch — Console
    "switch lite":           {"min": 90, "max": 130},
    "nintendo switch":       {"min": 140, "max": 200},
    # PS4 — Jeux
    "the last of us":        {"min": 10, "max": 18},
    "god of war":            {"min": 10, "max": 18},
    "spider man":            {"min": 10, "max": 18},
    "spider-man":            {"min": 10, "max": 18},
    "red dead redemption 2": {"min": 15, "max": 25},
    "ghost of tsushima":     {"min": 15, "max": 25},
    "horizon zero dawn":     {"min": 8,  "max": 15},
    "uncharted 4":           {"min": 8,  "max": 15},
    "bloodborne":            {"min": 18, "max": 28},
    "dark souls":            {"min": 12, "max": 22},
    "sekiro":                {"min": 18, "max": 28},
    "elden ring":            {"min": 25, "max": 38},
    "persona 5":             {"min": 20, "max": 32},
    "detroit become human":  {"min": 8,  "max": 15},
    "death stranding":       {"min": 10, "max": 18},
    "days gone":             {"min": 10, "max": 18},
    "resident evil 7":       {"min": 8,  "max": 15},
    "resident evil village": {"min": 15, "max": 25},
    "cyberpunk":             {"min": 10, "max": 18},
    "witcher 3":             {"min": 12, "max": 20},
    # PS4 — Manette
    "manette ps4":           {"min": 20, "max": 35},
    "dualshock":             {"min": 20, "max": 35},
    # Xbox
    "manette xbox":          {"min": 15, "max": 30},
    # Retrogaming
    "game boy advance sp":   {"min": 55, "max": 90},
    "game boy advance":      {"min": 35, "max": 60},
    "game boy color":        {"min": 45, "max": 75},
    "game boy pocket":       {"min": 30, "max": 55},
    "gameboy advance":       {"min": 35, "max": 60},
    "nintendo ds lite":      {"min": 25, "max": 45},
    "nintendo dsi":          {"min": 20, "max": 38},
    "nintendo ds":           {"min": 20, "max": 40},
    "new 3ds xl":            {"min": 80, "max": 130},
    "nintendo 3ds xl":       {"min": 60, "max": 100},
    "nintendo 3ds":          {"min": 40, "max": 75},
    "psp 3000":              {"min": 40, "max": 70},
    "psp":                   {"min": 30, "max": 60},
    "ps vita":               {"min": 60, "max": 110},
    "playstation vita":      {"min": 60, "max": 110},
    "playstation 1":         {"min": 30, "max": 60},
    "playstation 2":         {"min": 35, "max": 65},
    "nintendo 64":           {"min": 50, "max": 90},
    "super nintendo":        {"min": 55, "max": 95},
    "megadrive":             {"min": 40, "max": 75},
}

# Mots à rejeter dans le titre (faux positifs vestimentaires / autres)
BLACKLIST_TITRE = [
    "jas", "veste", "jacket", "shirt", "pantalon", "chaussure",
    "hoodie", "pull", "robe", "manteau", "apparel", "clothing",
    "shoes", "sneaker", "t-shirt", "tshirt", "jean", "short",
    "accessoire mode", "sac", "bag", "casquette", "bonnet",
    "figurine", "funko", "poster", "affiche", "livre", "guide",
    "boite vide", "boîte vide", "notice seule", "sans jeu",
]

# ═══════════════════════════════════════════════════════════
# DÉDUPLICATION
# ═══════════════════════════════════════════════════════════
seen_listings: set[str] = set()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# UTILITAIRES
# ═══════════════════════════════════════════════════════════

def uid(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:12]


def trouver_cote(titre: str) -> Optional[dict]:
    """Match le titre contre COTES — retourne la première cote trouvée."""
    t = titre.lower()
    # Tri par longueur de clé décroissante pour matcher le plus précis en premier
    for cle in sorted(COTES.keys(), key=len, reverse=True):
        if all(mot in t for mot in cle.split()):
            return COTES[cle]
    return None


def est_vetement(titre: str) -> bool:
    t = titre.lower()
    return any(m in t for m in BLACKLIST_TITRE)


def calculer_marge(prix_achat: float, cote: dict) -> dict:
    frais_port   = 4.5
    prix_median  = (cote["min"] + cote["max"]) / 2
    prix_vente   = prix_median * 0.92          # légèrement sous médiane
    benef_net    = prix_vente - prix_achat - frais_port
    marge_pct    = (benef_net / prix_achat * 100) if prix_achat > 0 else 0
    return {
        "prix_vente":  round(prix_vente, 1),
        "benef_net":   round(benef_net, 1),
        "marge_pct":   round(marge_pct, 0),
        "prix_median": round(prix_median, 1),
    }


def conseil_nego(prix: float, cote: dict, marge: dict) -> str:
    """
    Retourne un conseil de négociation ou d'achat immédiat.
    Logique :
      - Si marge >= 120% → achat immédiat, ne pas négocier (risque de se faire couper)
      - Si marge 80-120% → proposer -10% max
      - Si marge 50-80% → proposer -15 à -20%, ou passer si refus
    """
    pct = marge["marge_pct"]
    prix_negocie_10 = round(prix * 0.90, 1)
    prix_negocie_20 = round(prix * 0.80, 1)

    if pct >= 120:
        return (
            f"⚡ *ACHAT IMMÉDIAT* — Ne négocie pas, la marge est déjà excellente.\n"
            f"   Quelqu'un d'autre peut l'acheter avant toi. Fonce."
        )
    elif pct >= 80:
        return (
            f"💬 *Négociation possible* — Propose *{prix_negocie_10}€* (-10%).\n"
            f"   Si refus → achète quand même, la marge reste très bonne."
        )
    else:
        return (
            f"🤝 *Tente une négo* — Propose *{prix_negocie_20}€* (-20%).\n"
            f"   Si refus → achat OK mais vérifie bien l'état avant."
        )


def formater_alerte(titre: str, plateforme: str, localisation: str,
                    prix: float, cote: dict, marge: dict, url: str,
                    age_min: Optional[int] = None) -> str:
    emoji_marge = "🔥" if marge["marge_pct"] >= 100 else "✅"
    age_str = f"🕐 Postée il y a *{age_min} min*\n" if age_min is not None else ""
    return (
        f"🚨 *BONNE AFFAIRE DÉTECTÉE*\n\n"
        f"🎮 {titre}\n"
        f"📍 {plateforme} — {localisation}\n"
        f"{age_str}"
        f"💸 Prix annonce : *{prix}€*\n"
        f"📈 Cote marché : {cote['min']}-{cote['max']}€\n"
        f"{emoji_marge} Marge nette : *+{marge['benef_net']}€ ({int(marge['marge_pct'])}%)*\n"
        f"🎯 Prix revente conseillé : {marge['prix_vente']}€\n\n"
        f"{conseil_nego(prix, cote, marge)}\n\n"
        f"🔗 [Voir l'annonce]({url})"
    )


# ═══════════════════════════════════════════════════════════
# SCRAPER VINTED
# ═══════════════════════════════════════════════════════════

async def scraper_vinted(session: aiohttp.ClientSession, keyword: str) -> list[dict]:
    resultats = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }
    try:
        async with session.get("https://www.vinted.fr", headers=headers,
                               timeout=aiohttp.ClientTimeout(total=15)) as r:
            cookies = r.cookies

        api_url = (
            "https://www.vinted.fr/api/v2/catalog/items"
            f"?search_text={keyword.replace(' ', '%20')}"
            "&catalog_ids=139&per_page=30&order=newest_first"
        )
        api_headers = {
            **headers,
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"https://www.vinted.fr/catalog?search_text={keyword.replace(' ', '+')}",
        }
        async with session.get(api_url, headers=api_headers, cookies=cookies,
                               timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status != 200:
                log.warning(f"Vinted {r.status} pour '{keyword}'")
                return []
            data = await r.json()

        maintenant = datetime.now(timezone.utc)
        for item in data.get("items", []):
            titre = item.get("title", "")
            if est_vetement(titre):
                continue

            # Prix
            prix_raw = item.get("price", {})
            prix = float(prix_raw.get("amount", 0)) if isinstance(prix_raw, dict) else float(prix_raw or 0)
            if prix <= 0:
                continue

            # Fraîcheur
            created_raw = item.get("created_at_ts") or item.get("updated_at_ts")
            age_min = None
            if created_raw:
                created = datetime.fromtimestamp(int(created_raw), tz=timezone.utc)
                age_min = int((maintenant - created).total_seconds() / 60)
                if age_min > MAX_AGE_MINUTES:
                    continue

            url = f"https://www.vinted.fr/items/{item.get('id')}"
            ville = item.get("user", {}).get("city", "France")
            resultats.append({
                "titre": titre, "prix": prix, "url": url,
                "plateforme": "Vinted", "localisation": ville,
                "age_min": age_min,
            })

        log.info(f"Vinted '{keyword}': {len(resultats)} résultat(s) récent(s)")
    except Exception as e:
        log.warning(f"Vinted error '{keyword}': {e}")
    return resultats


# ═══════════════════════════════════════════════════════════
# SCRAPER LEBONCOIN
# ═══════════════════════════════════════════════════════════

async def scraper_lbc(session: aiohttp.ClientSession, keyword: str) -> list[dict]:
    resultats = []
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
    }
    url = (
        f"https://www.leboncoin.fr/recherche"
        f"?category=8&text={keyword.replace(' ', '+')}&sort=time&order=desc"
    )
    try:
        async with session.get(url, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=20)) as r:
            if r.status != 200:
                log.warning(f"LBC {r.status} pour '{keyword}'")
                return []
            html = await r.text()

        soup = BeautifulSoup(html, "html.parser")
        script = soup.find("script", {"id": "__NEXT_DATA__"})
        if not script:
            return []

        next_data = json.loads(script.string)
        ads = (next_data.get("props", {})
                        .get("pageProps", {})
                        .get("searchData", {})
                        .get("ads", []))

        maintenant = datetime.now(timezone.utc)
        for ad in ads[:20]:
            titre = ad.get("subject", "")
            if est_vetement(titre):
                continue

            prix_list = ad.get("price", [])
            if not prix_list:
                continue
            prix = float(prix_list[0]) if isinstance(prix_list, list) else float(prix_list)
            if prix <= 0:
                continue

            # Fraîcheur
            date_str = ad.get("index_date") or ad.get("first_publication_date")
            age_min = None
            if date_str:
                try:
                    pub = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    age_min = int((maintenant - pub).total_seconds() / 60)
                    if age_min > MAX_AGE_MINUTES:
                        continue
                except Exception:
                    pass

            ad_url = "https://www.leboncoin.fr" + ad.get("url", "")
            ville = ad.get("location", {}).get("city", "France")
            resultats.append({
                "titre": titre, "prix": prix, "url": ad_url,
                "plateforme": "Leboncoin", "localisation": ville,
                "age_min": age_min,
            })

        log.info(f"LBC '{keyword}': {len(resultats)} résultat(s) récent(s)")
    except Exception as e:
        log.warning(f"LBC error '{keyword}': {e}")
    return resultats


# ═══════════════════════════════════════════════════════════
# SCRAPER EBAY (API officielle — activé quand EBAY_APP_ID dispo)
# ═══════════════════════════════════════════════════════════

async def scraper_ebay(session: aiohttp.ClientSession, keyword: str) -> list[dict]:
    if not EBAY_APP_ID:
        return []
    resultats = []
    params = {
        "OPERATION-NAME": "findItemsAdvanced",
        "SERVICE-VERSION": "1.0.0",
        "SECURITY-APPNAME": EBAY_APP_ID,
        "RESPONSE-DATA-FORMAT": "JSON",
        "keywords": keyword,
        "categoryId": "1249",
        "itemFilter(0).name": "Condition",      "itemFilter(0).value": "Used",
        "itemFilter(1).name": "ListingType",    "itemFilter(1).value": "FixedPrice",
        "itemFilter(2).name": "LocatedIn",      "itemFilter(2).value": "FR",
        "sortOrder": "StartTimeNewest",
        "paginationInput.entriesPerPage": "20",
    }
    try:
        async with session.get("https://svcs.ebay.com/services/search/FindingService/v1",
                               params=params, timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status != 200:
                return []
            data = await r.json()

        items = (data.get("findItemsAdvancedResponse", [{}])[0]
                     .get("searchResult", [{}])[0]
                     .get("item", []))

        maintenant = datetime.now(timezone.utc)
        for item in items:
            titre = item.get("title", [""])[0]
            if est_vetement(titre):
                continue
            prix = float(item.get("sellingStatus", [{}])[0]
                             .get("currentPrice", [{}])[0]
                             .get("__value__", 0))
            if prix <= 0:
                continue

            start_time = item.get("listingInfo", [{}])[0].get("startTime", [""])[0]
            age_min = None
            if start_time:
                try:
                    pub = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                    age_min = int((maintenant - pub).total_seconds() / 60)
                    if age_min > MAX_AGE_MINUTES:
                        continue
                except Exception:
                    pass

            item_url = item.get("viewItemURL", [""])[0]
            ville = item.get("location", ["France"])[0]
            resultats.append({
                "titre": titre, "prix": prix, "url": item_url,
                "plateforme": "eBay", "localisation": ville,
                "age_min": age_min,
            })
    except Exception as e:
        log.warning(f"eBay error '{keyword}': {e}")
    return resultats


# ═══════════════════════════════════════════════════════════
# CYCLE PRINCIPAL
# ═══════════════════════════════════════════════════════════

async def cycle(bot: Bot):
    alertes = 0
    async with aiohttp.ClientSession() as session:

        # Vinted — tous les keywords Vinted
        for kw in KEYWORDS_VINTED:
            annonces = await scraper_vinted(session, kw)
            for a in annonces:
                await traiter_annonce(bot, a)
                alertes += 1 if uid(a["url"]) not in seen_listings else 0
            await asyncio.sleep(1.5)

        # Leboncoin — keywords LBC
        for kw in KEYWORDS_LBC:
            annonces = await scraper_lbc(session, kw)
            for a in annonces:
                await traiter_annonce(bot, a)
            await asyncio.sleep(2)

        # eBay (quand dispo)
        if EBAY_APP_ID:
            for kw in KEYWORDS_LBC[:20]:  # subset suffisant
                annonces = await scraper_ebay(session, kw)
                for a in annonces:
                    await traiter_annonce(bot, a)
                await asyncio.sleep(1)

    log.info(f"✅ Cycle terminé")


async def traiter_annonce(bot: Bot, annonce: dict):
    global seen_listings
    u = uid(annonce["url"])
    if u in seen_listings:
        return

    cote = trouver_cote(annonce["titre"])
    if not cote:
        return

    marge = calculer_marge(annonce["prix"], cote)
    if marge["marge_pct"] < MARGE_MIN_PCT or marge["benef_net"] < 5:
        return

    msg = formater_alerte(
        titre=annonce["titre"],
        plateforme=annonce["plateforme"],
        localisation=annonce["localisation"],
        prix=annonce["prix"],
        cote=cote,
        marge=marge,
        url=annonce["url"],
        age_min=annonce.get("age_min"),
    )
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=msg,
            parse_mode="Markdown",
            disable_web_page_preview=False,
        )
        seen_listings.add(u)
        log.info(f"🚨 Alerte : {annonce['titre']} — {int(marge['marge_pct'])}% — {annonce['plateforme']}")
        await asyncio.sleep(0.5)
    except TelegramError as e:
        log.error(f"Telegram error: {e}")


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════

async def main():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        raise ValueError("TELEGRAM_TOKEN et TELEGRAM_CHAT_ID requis")

    bot = Bot(token=TELEGRAM_TOKEN)
    me = await bot.get_me()
    log.info(f"🤖 Bot connecté : @{me.username}")

    plateformes = "Vinted + Leboncoin" + (" + eBay" if EBAY_APP_ID else "")
    await bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=(
            f"🚀 *GamingFlip Bot v2 démarré*\n\n"
            f"🔍 *{len(KEYWORDS_VINTED) + len(KEYWORDS_LBC)} mots-clés* surveillés\n"
            f"📊 Plateformes : *{plateformes}*\n"
            f"⏱️ Scan toutes les *{SCRAPE_INTERVAL // 60} min*\n"
            f"🕐 Annonces filtrées : *< {MAX_AGE_MINUTES} min*\n"
            f"💰 Alerte si marge > *{MARGE_MIN_PCT}%*\n"
            f"💬 Conseil négociation : *activé*\n\n"
            f"_Let's flip_ 🎮"
        ),
        parse_mode="Markdown",
    )

    while True:
        log.info("🔍 Nouveau cycle...")
        try:
            await cycle(bot)
        except Exception as e:
            log.error(f"Erreur cycle : {e}")
        log.info(f"⏳ Pause {SCRAPE_INTERVAL}s...")
        await asyncio.sleep(SCRAPE_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
