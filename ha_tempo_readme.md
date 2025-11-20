# Home Assistant - Intégration EDF Tempo

Intégration pour afficher les couleurs Tempo dans Home Assistant avec **une seule entité** contenant tous les états.

## 📦 Installation

### Option 1 : Installation manuelle

1. Créez le dossier `custom_components/tempo/` dans votre configuration Home Assistant
2. Copiez-y les fichiers suivants :
   - `__init__.py`
   - `sensor.py` (renommez binary_sensor.py)
   - `config_flow.py`
   - `manifest.json`

### Option 2 : Via HACS (recommandé)

1. Ajoutez ce repository comme repository personnalisé dans HACS
2. Recherchez "EDF Tempo" et installez
3. Redémarrez Home Assistant

## ⚙️ Configuration

1. Allez dans **Paramètres** → **Appareils et services**
2. Cliquez sur **+ Ajouter une intégration**
3. Recherchez "EDF Tempo"
4. Validez (aucune configuration nécessaire)

## 🎯 L'entité unique

Une seule entité : `sensor.edf_tempo`

**État** : Affiche la couleur actuelle avec la période  
Exemples : `Rouge HP`, `Blanc HC`, `Bleu HP`

## 📊 Attributs disponibles

### Informations actuelles
- `current_hour` : Heure actuelle
- `current_period` : "HP" ou "HC"
- `is_hc` : true/false (heures creuses)
- `is_hp` : true/false (heures pleines)

### Jour actuel (J)
- `today_date` : Date (YYYY-MM-DD)
- `today_color` : "Rouge", "Blanc" ou "Bleu"
- `today_color_en` : "red", "white" ou "blue"
- `today_color_code` : 1 (bleu), 2 (blanc), 3 (rouge)
- `today_is_red` / `today_is_white` / `today_is_blue` : true/false

### Lendemain (J+1)
- `tomorrow_date` : Date (YYYY-MM-DD)
- `tomorrow_color` : "Rouge", "Blanc" ou "Bleu"
- `tomorrow_color_en` : "red", "white" ou "blue"
- `tomorrow_color_code` : 1, 2 ou 3
- `tomorrow_is_red` / `tomorrow_is_white` / `tomorrow_is_blue` : true/false

### Combinaisons pratiques
- `today_red_hp` / `today_red_hc` : true si jour rouge + période correspondante
- `today_white_hp` / `today_white_hc`
- `today_blue_hp` / `today_blue_hc`
- `tomorrow_red_hp` / `tomorrow_red_hc`
- `tomorrow_white_hp` / `tomorrow_white_hc`
- `tomorrow_blue_hp` / `tomorrow_blue_hc`

### Autres
- `season` : Saison actuelle (ex: "2024-2025")

## 🤖 Exemples d'automatisations

### 1. Limiter la consommation en jour rouge HP

```yaml
automation:
  - alias: "Économie jour rouge HP"
    trigger:
      - platform: state
        entity_id: sensor.edf_tempo
        attribute: today_red_hp
        to: true
    action:
      - service: climate.set_temperature
        target:
          entity_id: climate.chambre
        data:
          temperature: 18
      - service: switch.turn_off
        target:
          entity_id: switch.cumulus
```

### 2. Notification si demain sera rouge

```yaml
automation:
  - alias: "Alerte J+1 rouge"
    trigger:
      - platform: state
        entity_id: sensor.edf_tempo
        attribute: tomorrow_is_red
        to: true
    action:
      - service: notify.mobile_app
        data:
          title: "⚠️ Jour rouge demain"
          message: "Demain sera un jour rouge Tempo. Pensez à charger la voiture cette nuit !"
```

### 3. Basculement automatique en heures creuses

```yaml
automation:
  - alias: "Activation HC"
    trigger:
      - platform: state
        entity_id: sensor.edf_tempo
        attribute: is_hc
        to: true
    action:
      - service: switch.turn_on
        target:
          entity_id: 
            - switch.cumulus
            - switch.charge_voiture
      - service: climate.set_temperature
        target:
          entity_id: climate.salon
        data:
          temperature: 21
```

### 4. Template pour afficher la couleur dans l'interface

```yaml
# Dans un card markdown
type: markdown
content: |
  ## Tempo aujourd'hui
  Couleur : **{{ state_attr('sensor.edf_tempo', 'today_color') }}**
  Période : **{{ state_attr('sensor.edf_tempo', 'current_period') }}**
  
  ## Tempo demain
  Couleur : **{{ state_attr('sensor.edf_tempo', 'tomorrow_color') }}**
```

### 5. Utiliser les attributs dans les conditions

```yaml
automation:
  - alias: "Action complexe"
    trigger:
      - platform: time
        at: "20:00:00"
    condition:
      - condition: template
        value_template: "{{ state_attr('sensor.edf_tempo', 'tomorrow_is_red') }}"
    action:
      - service: script.preparation_jour_rouge
```

## 🔄 Fonctionnement automatique

L'intégration se met à jour **automatiquement** aux moments clés :

### Mises à jour programmées
- **6h00** : 🌅 Passage en Heures Pleines + Nouveau jour J
  - L'attribut `current_period` passe à "HP"
  - Les attributs `today_*_hp` deviennent actifs
  - Les attributs `today_*_hc` deviennent inactifs
  - La nouvelle couleur du jour est appliquée

- **7h00** : 📡 Récupération API de la couleur J+1
  - Appel à l'API RTE pour obtenir la couleur du lendemain
  - Mise à jour des attributs `tomorrow_*`

- **22h00** : 🌙 Passage en Heures Creuses
  - L'attribut `current_period` passe à "HC"
  - Les attributs `today_*_hc` deviennent actifs
  - Les attributs `today_*_hp` deviennent inactifs

### Vérifications continues
- **Toutes les 5 minutes** : Vérification de l'état pour détecter tout changement d'heure manqué

### Automatisations déclenchées automatiquement

Ces changements déclenchent vos automatisations **sans intervention** :

```yaml
# S'active automatiquement à 22h chaque soir
trigger:
  - platform: state
    entity_id: sensor.edf_tempo
    attribute: is_hc
    to: true

# S'active automatiquement à 6h si jour rouge
trigger:
  - platform: state
    entity_id: sensor.edf_tempo
    attribute: today_red_hp
    to: true
```

## 📱 Interface utilisateur

Vous pouvez créer un card personnalisé pour afficher joliment les infos :

```yaml
type: entities
title: EDF Tempo
entities:
  - entity: sensor.edf_tempo
    name: État actuel
  - type: attribute
    entity: sensor.edf_tempo
    attribute: today_color
    name: Couleur aujourd'hui
  - type: attribute
    entity: sensor.edf_tempo
    attribute: tomorrow_color
    name: Couleur demain
  - type: attribute
    entity: sensor.edf_tempo
    attribute: current_period
    name: Période
```

## 🎨 Template Sensor pour des sensors séparés (optionnel)

Si vous préférez avoir des sensors individuels, créez des template sensors :

```yaml
template:
  - binary_sensor:
      - name: "Jour Rouge HP"
        state: "{{ state_attr('sensor.edf_tempo', 'today_red_hp') }}"
        icon: mdi:flash-alert
        
      - name: "Demain Rouge"
        state: "{{ state_attr('sensor.edf_tempo', 'tomorrow_is_red') }}"
        icon: mdi:calendar-alert
```

## 🐛 Support

Pour signaler un bug ou demander une fonctionnalité, ouvrez une issue sur GitHub.

## 📄 Licence

ISC © 2025

---

**Adapté du plugin Homebridge Tempo par Christophe Bansart**
