"""
🎮 GamingFlip Bot v3 — IA-powered
Scrape Vinted + Leboncoin → Claude Sonnet analyse chaque annonce complète
(titre + description + prix) → Alerte Telegram si bonne affaire
"""

import os
import asyncio
import logging
import json
import re
import hashlib
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import aiohttp
from bs4 import BeautifulSoup
from telegram import Bot
from telegram.error import TelegramError

# ═══════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════
TELEGRAM_TOKEN    = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID  = os.getenv("TELEGRAM_CHAT_ID", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
EBAY_APP_ID       = os.getenv("EBAY_APP_ID", "")

MARGE_MIN_PCT   = 40    # Alerte si marge nette >= 40%
MAX_AGE_MINUTES = 10    # Annonces < 10 min seulement
SCRAPE_INTERVAL = 240   # Scan toutes les 4 min
MAX_CONCURRENT  = 5     # Appels Claude en parallèle max
TZ              = ZoneInfo("Europe/Paris")

# ═══════════════════════════════════════════════════════════════════
# MOTS-CLÉS DE SCRAPING
# Larges exprès — c'est Claude qui filtre, pas des regex
# ═══════════════════════════════════════════════════════════════════
KEYWORDS_VINTED = [
    # Switch
    "zelda switch", "mario switch", "pokemon switch", "nintendo switch jeu",
    "animal crossing switch", "splatoon switch", "kirby switch",
    "smash bros switch", "mario kart switch", "luigi switch",
    "xenoblade switch", "fire emblem switch", "metroid switch",
    "minecraft switch", "lot jeux switch", "nintendo switch lite",
    # PS4
    "jeu ps4", "the last of us ps4", "god of war ps4", "spider-man ps4",
    "red dead redemption ps4", "ghost of tsushima ps4", "elden ring ps4",
    "bloodborne ps4", "persona ps4", "lot jeux ps4", "manette ps4",
    # Xbox
    "manette xbox one", "lot jeux xbox",
    # GBA
    "game boy advance", "game boy color", "game boy pocket",
    "gameboy advance", "pokemon gameboy", "zelda gameboy",
    # DS / 3DS
    "nintendo ds", "nintendo ds lite", "nintendo dsi",
    "nintendo 3ds", "nintendo 3ds xl", "new 3ds",
    "lot jeux ds", "lot jeux 3ds", "pokemon ds",
    # PSP / Vita
    "psp console", "psp playstation", "ps vita", "playstation vita",
    "lot jeux psp",
    # Rétro
    "console ps1", "console ps2", "nintendo 64", "super nintendo",
    "megadrive console", "lot jeux ps1", "lot jeux ps2",
    # Lots
    "lot jeux video", "collection jeux video",
]

KEYWORDS_LBC = [
    "zelda switch", "mario kart switch", "pokemon switch", "animal crossing switch",
    "lot jeux switch", "console nintendo switch",
    "the last of us ps4", "god of war ps4", "elden ring ps4",
    "lot jeux ps4", "manette ps4",
    "game boy advance", "game boy color", "gameboy",
    "nintendo ds", "nintendo 3ds", "psp console",
    "console ps1", "console ps2", "nintendo 64", "super nintendo", "megadrive",
    "lot jeux video",
]

# ═══════════════════════════════════════════════════════════════════
# DÉDUPLICATION
# ═══════════════════════════════════════════════════════════════════
seen_listings: set[str] = set()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

claude_sem = asyncio.Semaphore(MAX_CONCURRENT)


# ═══════════════════════════════════════════════════════════════════
# UTILITAIRES
# ═══════════════════════════════════════════════════════════════════

def uid(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:12]


# ═══════════════════════════════════════════════════════════════════
# SYSTÈME CLAUDE — PROMPT EXPERT
# ═══════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """Tu es un expert en achat-revente de jeux vidéo et consoles d'occasion en France.
Tu analyses des annonces Vinted et Leboncoin pour détecter les bonnes affaires à flipper.

Cotes eBay France (objets vendus, juin 2026) :

CONSOLES :
- Nintendo Switch standard : 140-200€ | Switch Lite : 90-130€ | Switch OLED : 190-240€
- PS4 500Go : 90-130€ | PS4 Slim : 100-140€ | PS4 Pro : 140-190€
- Xbox One S : 70-110€
- Game Boy Advance SP : 55-90€ | GBA classique : 35-60€ | GBP : 30-55€
- Game Boy Color : 45-75€
- Nintendo DS Fat : 15-30€ | DS Lite : 25-45€ | DSi : 20-38€
- New 3DS XL : 80-130€ | 3DS XL : 60-100€ | 3DS : 40-75€
- PSP 3000 : 40-70€ | PSP 1000/2000 : 30-55€
- PS Vita : 60-110€
- PS1 : 30-60€ | PS2 : 35-65€
- Nintendo 64 : 50-90€ | Super Nintendo : 55-95€ | Megadrive : 40-75€

JEUX SWITCH (cartouche seule) :
- Zelda BotW / TotK : 28-48€
- Mario Kart 8 Deluxe : 28-38€
- Super Mario Odyssey : 22-32€ | Mario Bros Wonder : 32-42€
- Pokémon Écarlate/Violet : 28-38€ | Épée/Bouclier : 22-32€ | Arceus : 28-38€
- Animal Crossing New Horizons : 25-35€
- Splatoon 3 : 25-35€ | Smash Bros Ultimate : 28-38€
- Mario Party Superstars : 28-38€ | Mario 3D World : 28-38€
- Xenoblade Chronicles 3 : 30-45€ | Fire Emblem Engage : 30-45€
- Minecraft Switch : 28-38€ | Luigi's Mansion 3 : 28-38€

JEUX PS4 :
- The Last of Us 1 ou 2 : 10-18€ | God of War (2018) : 10-18€
- Spider-Man / Miles Morales PS4 : 10-18€
- Red Dead Redemption 2 : 15-25€ | Ghost of Tsushima : 15-25€
- Horizon Zero Dawn : 8-15€ | Horizon Forbidden West : 12-20€
- Bloodborne : 18-28€ | Elden Ring : 25-38€
- Persona 5 Royal : 20-32€ | Dark Souls 3 : 12-22€ | Sekiro : 18-28€
- Detroit Become Human : 8-15€ | Death Stranding : 10-18€
- Days Gone : 10-18€ | Resident Evil Village : 15-25€

MANETTES :
- DualShock 4 (PS4) occasion : 20-35€ | Manette Xbox One occasion : 15-30€

LOTS : évaluer chaque article individuellement, appliquer 60-70% de la somme.

RÈGLES DE CALCUL :
- Frais port à déduire : 4.5€ (Vinted) | 6€ (Leboncoin/remise main propre = 0€)
- Prix revente réaliste = 90% de la médiane de la fourchette cote
- Marge nette = prix_revente - prix_achat - frais_port
- Marge % = (marge_nette / prix_achat) × 100

NE PAS alerter pour :
- Accessoires seuls sans valeur de revente : housse, câble, chargeur, batterie, coque, étui, sac de transport
- Figurines, amiibo, cartes, DLC, codes, livres, guides, boîtes vides, notices
- Vêtements, chaussures
- Articles cassés (écran cassé, ne fonctionne pas, pour pièces) sauf si prix très bas et mentionné explicitement
- Articles dont le prix d'achat est déjà proche de la cote marché (marge < 40%)

CONSEIL NEGO :
- marge >= 120% → "⚡ ACHAT IMMÉDIAT — Ne négocie pas, quelqu'un peut te couper"
- marge 80-119% → "💬 Propose [prix_achat × 0.90]€ (-10%). Si refus → achète quand même"
- marge 40-79% → "🤝 Tente [prix_achat × 0.80]€ (-20%). Si refus → OK mais vérifie l'état"

Réponds UNIQUEMENT en JSON valide, sans markdown, sans texte avant ou après :
{
  "alerte": true,
  "objet_identifie": "description précise ex: Nintendo Switch standard 32Go HAC-001",
  "categorie": "console|jeu|manette|lot|accessoire|autre",
  "etat_estime": "excellent|bon|moyen|mauvais|inconnu",
  "cote_min": 140,
  "cote_max": 200,
  "prix_revente_conseille": 156,
  "marge_nette": 24.5,
  "marge_pct": 87,
  "conseil_nego": "💬 Propose 54€ (-10%). Si refus → achète quand même",
  "points_attention": "Vérifier que la batterie tient bien la charge",
  "raison_no_alert": null
}

Si alerte=false :
{
  "alerte": false,
  "objet_identifie": "Housse de transport Nintendo Switch",
  "categorie": "accessoire",
  "etat_estime": "inconnu",
  "cote_min": 0, "cote_max": 0,
  "prix_revente_conseille": 0,
  "marge_nette": 0, "marge_pct": 0,
  "conseil_nego": null,
  "points_attention": null,
  "raison_no_alert": "Accessoire sans valeur de revente significative"
}"""


# ═══════════════════════════════════════════════════════════════════
# APPEL CLAUDE API
# ═══════════════════════════════════════════════════════════════════

async def analyser_avec_claude(
    session: aiohttp.ClientSession,
    titre: str,
    description: str,
    prix: float,
    plateforme: str,
) -> Optional[dict]:
    if not ANTHROPIC_API_KEY:
        return None

    prompt = (
        f"Plateforme : {plateforme}\n"
        f"Titre : {titre}\n"
        f"Prix demandé : {prix}€\n"
        f"Description : {description.strip()[:800] or '(aucune description)'}\n\n"
        "Analyse cette annonce et retourne le JSON."
    )

    async with claude_sem:
        try:
            async with session.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-6",
                    "max_tokens": 500,
                    "system": SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=aiohttp.ClientTimeout(total=25),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    log.warning(f"Claude {resp.status}: {body[:200]}")
                    return None
                data = await resp.json()
                raw = data["content"][0]["text"].strip()
                raw = re.sub(r"```json|```", "", raw).strip()
                return json.loads(raw)
        except json.JSONDecodeError as e:
            log.warning(f"Claude JSON error: {e}")
            return None
        except Exception as e:
            log.warning(f"Claude error: {e}")
            return None


# ═══════════════════════════════════════════════════════════════════
# FETCH DESCRIPTIONS COMPLÈTES
# ═══════════════════════════════════════════════════════════════════

async def fetch_desc_vinted(session: aiohttp.ClientSession, item_id: str) -> str:
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Accept-Language": "fr-FR,fr;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
        }
        async with session.get(
            f"https://www.vinted.fr/api/v2/items/{item_id}",
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as r:
            if r.status != 200:
                return ""
            data = await r.json()
            return data.get("item", {}).get("description", "") or ""
    except Exception:
        return ""


async def fetch_desc_lbc(session: aiohttp.ClientSession, url: str) -> str:
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "fr-FR,fr;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
        }
        async with session.get(url, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status != 200:
                return ""
            html = await r.text()
        soup = BeautifulSoup(html, "html.parser")
        script = soup.find("script", {"id": "__NEXT_DATA__"})
        if not script:
            return ""
        data = json.loads(script.string)
        ad = (data.get("props", {})
                  .get("pageProps", {})
                  .get("ad", {}))
        return ad.get("body", "") or ""
    except Exception:
        return ""


# ═══════════════════════════════════════════════════════════════════
# FORMAT ALERTE TELEGRAM
# ═══════════════════════════════════════════════════════════════════

def formater_alerte(annonce: dict, analyse: dict) -> str:
    age_str = f"🕐 Postée il y a *{annonce['age_min']} min*\n" if annonce.get("age_min") is not None else ""
    etat_emoji = {"excellent": "🟢", "bon": "🟡", "moyen": "🟠", "mauvais": "🔴"}.get(
        analyse.get("etat_estime", "inconnu"), "⚪"
    )
    marge_pct = int(analyse.get("marge_pct", 0))
    emoji_marge = "🔥" if marge_pct >= 100 else "✅"
    points = f"\n⚠️ _{analyse['points_attention']}_" if analyse.get("points_attention") else ""

    return (
        f"🚨 *BONNE AFFAIRE DÉTECTÉE*\n\n"
        f"🎮 *{analyse['objet_identifie']}*\n"
        f"📍 {annonce['plateforme']} — {annonce['localisation']}\n"
        f"{age_str}"
        f"{etat_emoji} État estimé : {analyse.get('etat_estime', 'inconnu')}\n\n"
        f"💸 Prix annonce : *{annonce['prix']}€*\n"
        f"📈 Cote marché : {analyse['cote_min']}-{analyse['cote_max']}€\n"
        f"🎯 Prix revente conseillé : *{analyse['prix_revente_conseille']}€*\n"
        f"{emoji_marge} Marge nette : *+{analyse['marge_nette']}€ ({marge_pct}%)*\n\n"
        f"{analyse.get('conseil_nego', '')}"
        f"{points}\n\n"
        f"🔗 [Voir l'annonce]({annonce['url']})"
    )


# ═══════════════════════════════════════════════════════════════════
# SCRAPER VINTED
# ═══════════════════════════════════════════════════════════════════

async def scraper_vinted(session: aiohttp.ClientSession, keyword: str) -> list[dict]:
    resultats = []
    headers_nav = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }
    try:
        async with session.get("https://www.vinted.fr", headers=headers_nav,
                               timeout=aiohttp.ClientTimeout(total=15)) as r:
            cookies = r.cookies

        api_url = (
            "https://www.vinted.fr/api/v2/catalog/items"
            f"?search_text={keyword.replace(' ', '%20')}"
            "&catalog_ids=139&per_page=30&order=newest_first"
        )
        headers_api = {
            **headers_nav,
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"https://www.vinted.fr/catalog?search_text={keyword.replace(' ', '+')}",
        }
        async with session.get(api_url, headers=headers_api, cookies=cookies,
                               timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status != 200:
                log.warning(f"Vinted {r.status} '{keyword}'")
                return []
            data = await r.json()

        maintenant = datetime.now(timezone.utc)
        for item in data.get("items", []):
            titre = item.get("title", "")
            prix_raw = item.get("price", {})
            prix = float(prix_raw.get("amount", 0)) if isinstance(prix_raw, dict) else float(prix_raw or 0)
            if prix <= 0:
                continue

            created_raw = item.get("created_at_ts") or item.get("updated_at_ts")
            age_min = None
            if created_raw:
                created = datetime.fromtimestamp(int(created_raw), tz=timezone.utc)
                age_min = int((maintenant - created).total_seconds() / 60)
                if age_min > MAX_AGE_MINUTES:
                    continue

            item_id = str(item.get("id", ""))
            url = f"https://www.vinted.fr/items/{item_id}"
            ville = item.get("user", {}).get("city", "France")
            desc = item.get("description", "") or ""

            resultats.append({
                "titre": titre, "prix": prix, "url": url,
                "plateforme": "Vinted", "localisation": ville,
                "age_min": age_min, "item_id": item_id, "description": desc,
            })

        log.info(f"Vinted '{keyword}': {len(resultats)} annonce(s) récente(s)")
    except Exception as e:
        log.warning(f"Vinted error '{keyword}': {e}")
    return resultats


# ═══════════════════════════════════════════════════════════════════
# SCRAPER LEBONCOIN
# ═══════════════════════════════════════════════════════════════════

async def scraper_lbc(session: aiohttp.ClientSession, keyword: str) -> list[dict]:
    resultats = []
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
    }
    url = f"https://www.leboncoin.fr/recherche?category=8&text={keyword.replace(' ', '+')}&sort=time&order=desc"
    try:
        async with session.get(url, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=20)) as r:
            if r.status != 200:
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
            prix_list = ad.get("price", [])
            if not prix_list:
                continue
            prix = float(prix_list[0]) if isinstance(prix_list, list) else float(prix_list)
            if prix <= 0:
                continue

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
            desc = ad.get("body", "") or ""

            resultats.append({
                "titre": titre, "prix": prix, "url": ad_url,
                "plateforme": "Leboncoin", "localisation": ville,
                "age_min": age_min, "item_id": None, "description": desc,
            })

        log.info(f"LBC '{keyword}': {len(resultats)} annonce(s) récente(s)")
    except Exception as e:
        log.warning(f"LBC error '{keyword}': {e}")
    return resultats


# ═══════════════════════════════════════════════════════════════════
# TRAITEMENT D'UNE ANNONCE
# ═══════════════════════════════════════════════════════════════════

async def traiter_annonce(bot: Bot, session: aiohttp.ClientSession, annonce: dict):
    u = uid(annonce["url"])
    if u in seen_listings:
        return

    # Enrichit la description si courte
    description = annonce.get("description", "")
    if len(description) < 30:
        if annonce["plateforme"] == "Vinted" and annonce.get("item_id"):
            description = await fetch_desc_vinted(session, annonce["item_id"])
        elif annonce["plateforme"] == "Leboncoin":
            description = await fetch_desc_lbc(session, annonce["url"])

    # Analyse par Claude
    analyse = await analyser_avec_claude(
        session=session,
        titre=annonce["titre"],
        description=description,
        prix=annonce["prix"],
        plateforme=annonce["plateforme"],
    )

    seen_listings.add(u)  # Marquer vu dans tous les cas

    if not analyse:
        log.warning(f"Analyse échouée : {annonce['titre'][:50]}")
        return

    if not analyse.get("alerte", False):
        log.info(f"❌ {annonce['titre'][:40]} — {analyse.get('raison_no_alert', '?')}")
        return

    marge = analyse.get("marge_pct", 0)
    if marge < MARGE_MIN_PCT:
        log.info(f"⚠️ Marge {marge}% trop faible : {annonce['titre'][:40]}")
        return

    # Envoie l'alerte Telegram
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=formater_alerte(annonce, analyse),
            parse_mode="Markdown",
            disable_web_page_preview=False,
        )
        log.info(f"🚨 ALERTE : {analyse['objet_identifie']} — {int(marge)}% — {annonce['plateforme']}")
        await asyncio.sleep(0.5)
    except TelegramError as e:
        log.error(f"Telegram error: {e}")


# ═══════════════════════════════════════════════════════════════════
# CYCLE PRINCIPAL
# ═══════════════════════════════════════════════════════════════════

async def cycle(bot: Bot):
    async with aiohttp.ClientSession() as session:
        toutes: list[dict] = []

        for kw in KEYWORDS_VINTED:
            toutes.extend(await scraper_vinted(session, kw))
            await asyncio.sleep(1.5)

        for kw in KEYWORDS_LBC:
            toutes.extend(await scraper_lbc(session, kw))
            await asyncio.sleep(2)

        # Déduplique AVANT d'appeler Claude (économie de tokens)
        uniques: dict[str, dict] = {}
        for a in toutes:
            u = uid(a["url"])
            if u not in seen_listings and u not in uniques:
                uniques[u] = a

        log.info(f"🧠 {len(uniques)} annonces uniques → Claude")

        # Traitement par batch de MAX_CONCURRENT
        annonces_list = list(uniques.values())
        for i in range(0, len(annonces_list), MAX_CONCURRENT):
            batch = annonces_list[i:i + MAX_CONCURRENT]
            await asyncio.gather(
                *[traiter_annonce(bot, session, a) for a in batch],
                return_exceptions=True,
            )
            await asyncio.sleep(1)

    log.info("✅ Cycle terminé")


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

async def main():
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        raise ValueError("TELEGRAM_TOKEN et TELEGRAM_CHAT_ID requis")
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY requis — ajoute-la dans Railway Variables")

    bot = Bot(token=TELEGRAM_TOKEN)
    me = await bot.get_me()
    log.info(f"🤖 Bot connecté : @{me.username}")

    plateformes = "Vinted + Leboncoin" + (" + eBay" if EBAY_APP_ID else "")
    await bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=(
            "🚀 *GamingFlip Bot v3 — IA activée*\n\n"
            f"🧠 Analyse : *Claude Sonnet*\n"
            f"🔍 *{len(KEYWORDS_VINTED) + len(KEYWORDS_LBC)} mots-clés* surveillés\n"
            f"📊 Plateformes : *{plateformes}*\n"
            f"⏱️ Scan toutes les *{SCRAPE_INTERVAL // 60} min*\n"
            f"🕐 Filtre fraîcheur : *< {MAX_AGE_MINUTES} min*\n"
            f"💰 Alerte si marge > *{MARGE_MIN_PCT}%*\n"
            f"💬 Conseil négociation : *activé*\n\n"
            "_Let's flip_ 🎮"
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
