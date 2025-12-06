# ⏰ Chronologie automatique - Intégration Tempo

## 📅 Exemple sur 24h (Jour Rouge)

```
┌─────────────────────────────────────────────────────────────┐
│                    JOUR J (Rouge)                            │
└─────────────────────────────────────────────────────────────┘

00:00 ─┐
       │  🌙 Heures Creuses
       │  • is_hc = true
       │  • today_is_red_hc = true
       │  • Cumulus ON
       │  • Charge voiture ON
05:59 ─┘

06:00 ─┐  🔄 DÉCLENCHEMENT AUTOMATIQUE #1
       │  ═══════════════════════════════
       │  ✅ Passage en Heures Pleines
       │  ✅ Nouveau jour J appliqué
       │
       │  États mis à jour:
       │  • is_hc = false → is_hp = true
       │  • today_is_red_hc = false
       │  • today_is_red_hp = true ⚠️
       │
       │  🤖 Automatisations déclenchées:
       │  → "Tempo - Début jour rouge HP"
       │    ├─ Notification "Jour Rouge"
       │    ├─ Chauffage → 18°C
       │    ├─ Cumulus OFF
       │    └─ Charge voiture OFF
       │

07:00 ─┐  🔄 DÉCLENCHEMENT AUTOMATIQUE #2
       │  ═══════════════════════════════
       │  ✅ Récupération API couleur J+1
       │
       │  États mis à jour:
       │  • tomorrow_color = "Blanc"
       │  • tomorrow_is_red = false
       │  • tomorrow_is_white = true
       │
       │  🤖 Automatisations déclenchées:
       │  → "Tempo - Info demain bleu"
       │    └─ Notification "Demain Blanc"
       │

       │  🌅 Heures Pleines (Rouge)
       │  • Économies d'énergie actives
       │  • Chauffage réduit
       │  • Gros appareils éteints
       │

21:59 ─┘

22:00 ─┐  🔄 DÉCLENCHEMENT AUTOMATIQUE #3
       │  ═══════════════════════════════
       │  ✅ Passage en Heures Creuses
       │
       │  États mis à jour:
       │  • is_hp = false → is_hc = true
       │  • today_is_red_hp = false
       │  • today_is_red_hc = true
       │
       │  🤖 Automatisations déclenchées:
       │  → "Tempo - Passage en heures creuses"
       │    ├─ Notification "HC activées"
       │    ├─ Cumulus ON
       │    ├─ Charge voiture ON
       │    └─ Chauffage → 20°C
       │
       │  → "Tempo - Jour rouge HC"
       │    └─ Charge maximale appareils
       │

23:59 ─┘  🌙 Heures Creuses
          • Tous les appareils rechargés
          • Profiter du tarif avantageux

┌─────────────────────────────────────────────────────────────┐
│                    JOUR J+1 (Blanc)                          │
└─────────────────────────────────────────────────────────────┘

06:00      🔄 Nouveau cycle commence...
```

## 🎯 Points de déclenchement automatiques

### 1️⃣ 6h00 - Passage HP + Nouveau jour

**Déclencheur :** `async_track_time_change(hour=6)`

**Ce qui se passe :**

```python
is_hp = True
is_hc = False
today_color = nouvelle_couleur
today_is_*_hp = True ou False selon couleur
today_is_*_hc = False
```

**Automatisations déclenchées par :**

- `attribute: today_is_red_hp` → `to: true`
- `attribute: today_is_white_hp` → `to: true`
- `attribute: today_is_blue_hp` → `to: true`
- `attribute: is_hp` → `to: true`

### 2️⃣ 7h00 - Récupération J+1

**Déclencheur :** `async_track_time_change(hour=7)`

**Ce qui se passe :**

```python
Appel API RTE
tomorrow_color = couleur_j1
tomorrow_is_red = True ou False
tomorrow_is_white = True ou False
tomorrow_is_blue = True ou False
```

**Automatisations déclenchées par :**

- `attribute: tomorrow_is_red` → `to: true`
- `attribute: tomorrow_is_white` → `to: true`
- `attribute: tomorrow_is_blue` → `to: true`

### 3️⃣ 22h00 - Passage HC

**Déclencheur :** `async_track_time_change(hour=22)`

**Ce qui se passe :**

```python
is_hc = True
is_hp = False
today_is_*_hp = False
today_is_*_hc = True ou False selon couleur
```

**Automatisations déclenchées par :**

- `attribute: today_is_red_hc` → `to: true`
- `attribute: today_is_white_hc` → `to: true`
- `attribute: today_is_blue_hc` → `to: true`
- `attribute: is_hc` → `to: true`

### 4️⃣ Toutes les 5 minutes - Vérification

**Déclencheur :** `update_interval=timedelta(minutes=5)`

**Objectif :**

- Détecter tout changement d'heure manqué
- Assurer la cohérence des états
- Backup des déclenchements programmés

## 🛡️ Sécurités et fiabilité

### Protection contre les défaillances

```python
# Si HA redémarre entre 22h et 6h
→ Au démarrage: détection automatique is_hc = True
→ États cohérents immédiatement

# Si l'API RTE est indisponible
→ Retry automatique 1h plus tard
→ Les couleurs J restent valides

# Si déclenchement 6h ou 22h manqué
→ Check toutes les 5 min détecte le changement
→ Mise à jour forcée des entités
```

### Logs de suivi

À chaque événement clé :

```
[INFO] Changement de période détecté: HP → HC
[INFO] Données Tempo mises à jour: J=Rouge (3), J+1=Blanc (2) [Passage HC]
[INFO] Mises à jour programmées: 6h (passage HP), 7h (API J+1), 22h (passage HC)
```

## 📱 Exemple réel d'utilisation

### Scénario : Jour Rouge

**05:59** - Vous dormez

- Voiture en charge
- Cumulus chauffe
- Chauffage normal 20°C

**06:00** - Déclenchement automatique ⚡

- Notification sur téléphone "⚠️ Jour Rouge"
- Chauffage baisse à 18°C
- Cumulus s'éteint
- Charge voiture s'arrête
- **Vous n'avez rien fait !**

**12:00** - Journée

- Pas de lavage
- Pas de cuisson four longue
- Économies automatiques

**22:00** - Déclenchement automatique ⚡

- Notification "🌙 Heures Creuses"
- Cumulus redémarre
- Voiture recharge
- Chauffage remonte à 20°C
- **Vous n'avez rien fait !**

**Le lendemain 06:00** - Fin du jour rouge

- Retour à la normale automatique

## 💡 Pas d'intervention manuelle requise

✅ Tous les déclenchements sont **automatiques**
✅ Les automatisations se lancent **toutes seules**
✅ Vous êtes juste **notifié** des changements
✅ Vous pouvez **superviser** via le dashboard
