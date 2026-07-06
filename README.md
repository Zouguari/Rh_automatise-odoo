# Assistant RH & Recrutement IA - Odoo 17

Ce projet contient l'environnement de développement pour le module Odoo 17 d'**Assistant RH & Recrutement IA**.

L'architecture utilise Docker pour simplifier le lancement d'Odoo et PostgreSQL, garantissant que tous les collaborateurs travaillent sur le même environnement.

---

## 📋 Prérequis

Avant de commencer, assurez-vous d'avoir installé sur votre machine :
- **Git**
- **Docker** et **Docker Compose**
- Un IDE comme **VS Code**

---

## 🚀 Démarrage Rapide (Pour vous et vos camarades)

### 1. Cloner ce dépôt
Clonez ce projet (le dépôt GitHub que vous allez créer pour votre équipe) dans votre espace de travail :
```bash
git clone <URL_DE_VOTRE_DEPOT_GITHUB> Rh_automatise
cd Rh_automatise
```

### 2. Cloner Odoo 17 en local (Pour l'aide au développement / Auto-complétion)
Pour que votre éditeur de code (VS Code) reconnaisse le code Odoo et propose l'autocomplétion lors du développement, clonez le dépôt officiel d'Odoo dans le dossier `odoo` (ce dossier est ignoré par Git via `.gitignore`) :
```bash
git clone https://github.com/odoo/odoo.git --depth 1 --branch 17.0 odoo
```

### 3. Lancer l'environnement avec Docker
Démarrez les conteneurs d'Odoo 17 et PostgreSQL 15 en arrière-plan :
```bash
docker compose up -d
```

### 4. Accéder à Odoo et installer le module
1. Ouvrez votre navigateur et allez sur : [http://localhost:8070](http://localhost:8070)
2. Créez une nouvelle base de données (si demandé).
3. Connectez-vous, puis allez dans **Configuration (Settings)** -> Tout en bas, cliquez sur **Activer le mode développeur**.
4. Allez dans le menu **Applications**.
5. Cliquez sur **Mettre à jour la liste des applications (Update Apps List)** dans la barre supérieure.
6. Recherchez `Assistant RH` ou `hr_recruitment_ai_assistant`.
7. Cliquez sur **Activer (Install)**.

---

## 🛠️ Structure du Projet

- `custom_addons/` : Contient vos modules personnalisés. C'est ici que vous écrirez votre code.
  - `hr_recruitment_ai_assistant/` : Le module de base (squelette d'origine).
- `odoo/` : Code source officiel d'Odoo (non poussé sur Git). Sert uniquement de référence locale.
- `docker-compose.yml` : Configuration Docker.
- `.gitignore` : Configuration d'exclusion Git.
