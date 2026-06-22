"""
🎮 GamingFlip Bot — Alertes achat-revente gaming
Scrape eBay FR + Vinted en continu, alerte sur Telegram si marge > 50%
"""

import os
import asyncio
import logging
import json
import re
import hashlib
from datetime import datetime
from typing import Optional

import aiohttp
from bs4 import BeautifulSoup
from telegram import Bot
from telegram.error import TelegramError

# ─────────────────────────────────────────
# CONFIG — à remplir dans .env
# ─────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
EBAY_APP_ID = os.getenv("EBAY_APP_ID", "")  # Compte développeur eBay gratuit

# Marge minimum pour déclencher une alerte (en %)
MARGE_MIN_PCT = 50

# Intervalle entre chaque cycle de scraping (en secondes)
SCRAPE_INTERVAL = 300  # 5 minutes

# ─────────────────────────────────────────
# MOTS-CLÉS À SURVEILLER
# Modifier selon tes cibles du moment
# ─────────────────────────────────────────
KEYWORDS = [
    # Switch
    "zelda switch", "mario kart switch", "super mario odyssey", "pokemon switch",
    "nintendo switch jeu", "mario odyssey",
    # PS4
    "the last of us ps4", "god of war ps4", "spider-man ps4", "rdr2 ps4",
    "red dead redemption ps4",
    # Retrogaming
    "game boy color", "game boy advance", "gba", "gameboy advance",
    "nintendo ds", "psp", "playstation 1", "ps1",
    # Manettes
    "manette ps4", "manette xbox one",
    # Lots
    "lot jeux switch", "lot jeux ps4", "lot jeux ds",
]

# ─────────────────────────────────────────
# COTES DE RÉFÉRENCE (eBay FR vendus)
# À maintenir et enrichir au fil du temps
# ─────────────────────────────────────────
COTES_REFERENCE = {
    "zelda breath of the wild switch": {"min": 28, "max": 38},
    "zelda tears of the kingdom": {"min": 35, "max": 48},
    "mario kart 8 deluxe": {"min": 28, "max": 38},
    "super mario odyssey": {"min": 22, "max": 32},
    "pokemon ecarlate": {"min": 28, "max": 38},
    "pokemon violet": {"min": 28, "max": 38},
    "the last of us ps4": {"min": 10, "max": 18},
    "god of war ps4": {"min": 10, "max": 18},
    "spider-man ps4": {"min": 10, "max": 18},
    "red dead redemption 2 ps4": {"min": 15, "max": 25},
    "game boy color": {"min": 45, "max": 75},
    "game boy advance": {"min": 35, "max": 60},
    "nintendo ds": {"min": 20, "max": 40},
    "psp": {"min": 30, "max": 60},
    "manette ps4": {"min": 20, "max": 35},
    "manette xbox one": {"min": 15, "max": 28},
}

# ─────────────────────────────────────────
# DÉDUPLICATION — évite d'alerter 2x la même annonce
# ─────────────────────────────────────────
seen_listings = set()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────
# UTILITAIRES
# ─────────────────────────────────────────

def listing_id(url: str) -> str:
    """Hash court d'une URL pour déduplication."""
    return hashlib.md5(url.encode()).hexdigest()[:12]


def extraire_prix(texte: str) -> Optional[float]:
    """Extrait un prix numérique depuis une chaîne."""
    match = re.search(r"(\d+[.,]\d{0,2}|\d+)", texte.replace("\xa0", ""))
    if match:
        return float(match.group(1).replace(",", "."))
    return None


def calculer_marge(prix_achat: float, cote_min: float, cote_max: float) -> dict:
    """Calcule marge nette en tenant compte des frais Vinted (0%) et port estimé."""
    frais_port = 4.5  # estimation Vinted standard
    prix_vente_cible = (cote_min + cote_max) / 2 * 0.90  # légèrement sous la médiane
    benefice_net = prix_vente_cible - prix_achat - frais_port
    marge_pct = (benefice_net / prix_achat) * 100 if prix_achat > 0 else 0
    return {
        "prix_vente_cible": round(prix_vente_cible, 1),
        "benefice_net": round(benefice_net, 1),
        "marge_pct": round(marge_pct, 0),
    }


def trouver_cote(titre: str) -> Optional[dict]:
    """Cherche la cote la plus proche dans COTES_REFERENCE."""
    titre_lower = titre.lower()
    for cle, cote in COTES_REFERENCE.items():
        if all(mot in titre_lower for mot in cle.split()):
            return cote
    # Essai partiel (au moins 2 mots clés qui matchent)
    for cle, cote in COTES_REFERENCE.items():
        mots = cle.split()
        if len(mots) >= 2 and sum(1 for m in mots if m in titre_lower) >= 2:
            return cote
    return None


# ─────────────────────────────────────────
# FORMAT MESSAGE TELEGRAM
# ─────────────────────────────────────────

def formater_alerte(titre: str, plateforme: str, localisation: str,
                    prix: float, cote: dict, marge: dict, url: str) -> str:
    emoji_marge = "🔥" if marge["marge_pct"] >= 100 else "✅"
    return (
        f"🚨 *BONNE AFFAIRE DÉTECTÉE*\n\n"
        f"🎮 {titre}\n"
        f"📍 {plateforme} — {localisation}\n"
        f"💸 Prix annonce : *{prix}€*\n"
        f"📈 Cote revente : {cote['min']}-{cote['max']}€\n"
        f"{emoji_marge} Marge estimée : *+{marge['benefice_net']}€ ({int(marge['marge_pct'])}%)*\n"
        f"🎯 Prix vente conseillé : {marge['prix_vente_cible']}€\n"
        f"🔗 [Voir l'annonce]({url})"
    )


# ─────────────────────────────────────────
# SCRAPER VINTED
# ─────────────────────────────────────────

async def scraper_vinted(session: aiohttp.ClientSession, keyword: str) -> list[dict]:
    """Scrape Vinted France pour un mot-clé donné."""
    resultats = []
    url = (
        f"https://www.vinted.fr/api/v2/catalog/items"
        f"?search_text={keyword.replace(' ', '+')}"
        f"&catalog_ids=&per_page=20&order=newest_first"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            items = data.get("items", [])
            for item in items:
                titre = item.get("title", "")
                prix_str = item.get("price", {})
                if isinstance(prix_str, dict):
                    prix = float(prix_str.get("amount", 0))
                else:
                    prix = float(prix_str or 0)
                item_url = f"https://www.vinted.fr/items/{item.get('id')}"
                ville = item.get("user", {}).get("city", "France")
                if prix > 0:
                    resultats.append({
                        "titre": titre,
                        "prix": prix,
                        "url": item_url,
                        "plateforme": "Vinted",
                        "localisation": ville,
                    })
    except Exception as e:
        log.warning(f"Vinted scraping error ({keyword}): {e}")
    return resultats


# ─────────────────────────────────────────
# SCRAPER EBAY (API Finding officielle)
# ─────────────────────────────────────────

async def scraper_ebay(session: aiohttp.ClientSession, keyword: str) -> list[dict]:
    """Scrape eBay France via l'API Finding gratuite."""
    if not EBAY_APP_ID:
        return []
    resultats = []
    url = "https://svcs.ebay.com/services/search/FindingService/v1"
    params = {
        "OPERATION-NAME": "findItemsAdvanced",
        "SERVICE-VERSION": "1.0.0",
        "SECURITY-APPNAME": EBAY_APP_ID,
        "RESPONSE-DATA-FORMAT": "JSON",
        "REST-PAYLOAD": "",
        "keywords": keyword,
        "categoryId": "1249",  # Jeux vidéo
        "itemFilter(0).name": "Condition",
        "itemFilter(0).value": "Used",
        "itemFilter(1).name": "ListingType",
        "itemFilter(1).value": "FixedPrice",
        "itemFilter(2).name": "LocatedIn",
        "itemFilter(2).value": "FR",
        "sortOrder": "StartTimeNewest",
        "paginationInput.entriesPerPage": "20",
    }
    try:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            items = (
                data.get("findItemsAdvancedResponse", [{}])[0]
                    .get("searchResult", [{}])[0]
                    .get("item", [])
            )
            for item in items:
                titre = item.get("title", [""])[0]
                prix = float(item.get("sellingStatus", [{}])[0]
                               .get("currentPrice", [{}])[0]
                               .get("__value__", 0))
                item_url = item.get("viewItemURL", [""])[0]
                ville = item.get("location", ["France"])[0]
                if prix > 0:
                    resultats.append({
                        "titre": titre,
                        "prix": prix,
                        "url": item_url,
                        "plateforme": "eBay",
                        "localisation": ville,
                    })
    except Exception as e:
        log.warning(f"eBay scraping error ({keyword}): {e}")
    return resultats


# ─────────────────────────────────────────
# SCRAPER LEBONCOIN (via RSS / alertes)
# ─────────────────────────────────────────

async def scraper_leboncoin_rss(session: aiohttp.ClientSession, keyword: str) -> list[dict]:
    """
    Leboncoin ne propose pas d'API publique.
    Cette fonction parse le flux RSS de recherche (limité mais fonctionnel).
    Alternative recommandée : activer les alertes email LBC et les parser.
    """
    resultats = []
    # LBC bloque le scraping direct — on utilise une URL de recherche encodée
    url = f"https://www.leboncoin.fr/recherche?category=8&text={keyword.replace(' ', '+')}&sort=time&order=desc"
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
    }
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return []
            html = await resp.text()
            soup = BeautifulSoup(html, "html.parser")
            # LBC rend en JSON dans __NEXT_DATA__
            script = soup.find("script", {"id": "__NEXT_DATA__"})
            if not script:
                return []
            next_data = json.loads(script.string)
            ads = (next_data.get("props", {})
                           .get("pageProps", {})
                           .get("searchData", {})
                           .get("ads", []))
            for ad in ads[:15]:
                titre = ad.get("subject", "")
                prix = ad.get("price", [None])
                prix = prix[0] if isinstance(prix, list) and prix else prix
                if not isinstance(prix, (int, float)):
                    continue
                ad_url = "https://www.leboncoin.fr" + ad.get("url", "")
                localisation = ad.get("location", {}).get("city", "France")
                resultats.append({
                    "titre": titre,
                    "prix": float(prix),
                    "url": ad_url,
                    "plateforme": "Leboncoin",
                    "localisation": localisation,
                })
    except Exception as e:
        log.warning(f"Leboncoin scraping error ({keyword}): {e}")
    return resultats


# ─────────────────────────────────────────
# MOTEUR PRINCIPAL — 1 cycle de scraping
# ─────────────────────────────────────────

async def cycle_scraping(bot: Bot):
    """Un cycle complet : scrape toutes les plateformes, analyse, alerte."""
    alertes_envoyees = 0

    async with aiohttp.ClientSession() as session:
        for keyword in KEYWORDS:
            annonces = []

            # Scraping multi-plateforme
            vinted = await scraper_vinted(session, keyword)
            ebay = await scraper_ebay(session, keyword)
            lbc = await scraper_leboncoin_rss(session, keyword)
            annonces = vinted + ebay + lbc

            for annonce in annonces:
                uid = listing_id(annonce["url"])
                if uid in seen_listings:
                    continue

                cote = trouver_cote(annonce["titre"])
                if not cote:
                    continue

                marge = calculer_marge(annonce["prix"], cote["min"], cote["max"])

                if marge["marge_pct"] >= MARGE_MIN_PCT and marge["benefice_net"] >= 5:
                    msg = formater_alerte(
                        titre=annonce["titre"],
                        plateforme=annonce["plateforme"],
                        localisation=annonce["localisation"],
                        prix=annonce["prix"],
                        cote=cote,
                        marge=marge,
                        url=annonce["url"],
                    )
                    try:
                        await bot.send_message(
                            chat_id=TELEGRAM_CHAT_ID,
                            text=msg,
                            parse_mode="Markdown",
                            disable_web_page_preview=False,
                        )
                        seen_listings.add(uid)
                        alertes_envoyees += 1
                        log.info(f"✅ Alerte envoyée : {annonce['titre']} ({int(marge['marge_pct'])}%)")
                        await asyncio.sleep(1)  # anti-flood Telegram
                    except TelegramError as e:
                        log.error(f"Telegram error: {e}")

            await asyncio.sleep(2)  # anti-ban entre les keywords

    log.info(f"Cycle terminé — {alertes_envoyees} alerte(s) envoyée(s)")


# ─────────────────────────────────────────
# BOUCLE PRINCIPALE
# ─────────────────────────────────────────

async def main():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        raise ValueError("❌ TELEGRAM_TOKEN et TELEGRAM_CHAT_ID requis dans .env")

    bot = Bot(token=TELEGRAM_TOKEN)
    me = await bot.get_me()
    log.info(f"🤖 Bot connecté : @{me.username}")

    # Message de démarrage
    await bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=(
            "🚀 *GamingFlip Bot démarré*\n\n"
            f"🔍 Surveillance de *{len(KEYWORDS)} mots-clés*\n"
            f"📊 Plateformes : Vinted, eBay, Leboncoin\n"
            f"⏱️ Scan toutes les *{SCRAPE_INTERVAL // 60} min*\n"
            f"💰 Alerte si marge > *{MARGE_MIN_PCT}%*\n\n"
            "_Let's flip_ 🎮"
        ),
        parse_mode="Markdown",
    )

    while True:
        try:
            log.info("🔍 Démarrage d'un cycle de scraping...")
            await cycle_scraping(bot)
        except Exception as e:
            log.error(f"Erreur cycle : {e}")
        log.info(f"⏳ Pause {SCRAPE_INTERVAL}s avant le prochain cycle...")
        await asyncio.sleep(SCRAPE_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
