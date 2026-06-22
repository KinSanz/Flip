# 🎮 GamingFlip Bot — Setup complet

Bot Telegram qui scrape Vinted, eBay et Leboncoin en continu et t'alerte dès qu'une bonne affaire gaming dépasse 50% de marge.

---

## ÉTAPE 1 — Créer le bot Telegram (5 min)

1. Ouvre Telegram → recherche **@BotFather**
2. Tape `/newbot`
3. Nom affiché : `GamingFlip Bot`
4. Username : `RyanGamingFlipper_bot` (doit se terminer par `_bot`)
5. **Copie le token** → format `123456789:AAF...`

### Récupérer ton Chat ID
1. Cherche **@userinfobot** sur Telegram
2. Tape `/start`
3. Il te donne ton **Id** (ex: `987654321`) → c'est ton TELEGRAM_CHAT_ID

---

## ÉTAPE 2 — Clé API eBay (10 min, gratuit)

1. Va sur **developer.ebay.com**
2. Crée un compte (gratuit)
3. Va dans **My Account → Application Keys**
4. Crée une app → copie l'**App ID (Client ID)** en production

---

## ÉTAPE 3 — Déploiement Railway (5 min)

### Option A — Via GitHub (recommandé)
1. Crée un repo GitHub privé
2. Push tous les fichiers dedans
3. Va sur **railway.app** → New Project → Deploy from GitHub
4. Sélectionne ton repo

### Option B — Via Railway CLI
```bash
npm install -g @railway/cli
railway login
railway init
railway up
```

### Configurer les variables d'environnement sur Railway
Dans ton projet Railway → **Variables** → ajoute :
```
TELEGRAM_TOKEN = ton_token_ici
TELEGRAM_CHAT_ID = ton_chat_id_ici
EBAY_APP_ID = ton_app_id_ebay
```

Railway redémarre automatiquement le bot dès que tu sauvegardes.

---

## ÉTAPE 4 — Test en local (optionnel)

```bash
# Copie .env.example en .env et remplis les valeurs
cp .env.example .env
nano .env

# Installe les dépendances
pip install -r requirements.txt

# Lance le bot
python bot.py
```

---

## Personnaliser les alertes

### Ajouter des mots-clés à surveiller
Dans `bot.py`, modifie la liste `KEYWORDS` :
```python
KEYWORDS = [
    "zelda switch",
    "mario kart switch",
    # Ajoute tes cibles ici
]
```

### Ajouter des cotes de référence
Dans `bot.py`, modifie `COTES_REFERENCE` :
```python
COTES_REFERENCE = {
    "zelda breath of the wild switch": {"min": 28, "max": 38},
    # Ajoute tes cotes ici (vérifie sur eBay vendus)
}
```

### Changer le seuil de marge
```python
MARGE_MIN_PCT = 50  # Alerte si marge > 50%
```

### Changer la fréquence de scan
```python
SCRAPE_INTERVAL = 300  # 5 minutes (en secondes)
```

---

## Format des alertes reçues

```
🚨 BONNE AFFAIRE DÉTECTÉE

🎮 Super Mario Odyssey Switch
📍 Vinted — Lyon
💸 Prix annonce : 12€
📈 Cote revente : 22-32€
✅ Marge estimée : +11€ (92%)
🎯 Prix vente conseillé : 24.3€
🔗 [Voir l'annonce]
```

---

## Coût mensuel estimé

| Service | Coût |
|---------|------|
| Railway (hobby plan) | ~5€/mois |
| Telegram Bot API | Gratuit |
| eBay Finding API | Gratuit |
| Vinted (non-officiel) | Gratuit |
| **Total** | **~5€/mois** |

---

## Roadmap

- [x] Mode auto — scraping continu + alertes
- [ ] Mode lien — analyse d'une annonce à la demande
- [ ] Mode photo — identification article + cote (Claude Vision)
- [ ] SaaS — multi-utilisateurs + abonnements
