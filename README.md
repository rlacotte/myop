# 🎙️ MYOP — My Own Podcast

**Ton propre podcast quotidien, livré chaque matin sur ton lecteur de podcast.**

MYOP agrège les flux RSS que tu choisis, rédige un briefing, le transforme en audio
(voix de synthèse Edge TTS, gratuit) et le publie automatiquement via GitHub Pages.
Tu t'abonnes **une seule fois** dans Apple Podcasts, Overcast ou Pocket Casts —
et tu reçois un nouvel épisode chaque matin.

```
Flux RSS (Le Monde, franceinfo…) ──► script de briefing ──► voix Edge TTS ──► MP3
                                                                        │
Toi ◄── Apple Podcasts / Overcast ◄── flux RSS (GitHub Pages) ◄── GitHub Actions (cron quotidien)
```

## ✨ Ce que fait l'app

- **Collecte** tes flux RSS (24 dernières heures, élargi à 48 h si besoin), dédoublonne
  les articles et répartit les sources (max. par source configurable)
- **Rédige** un script : intro datée → flash des titres → brèves détaillées → outro
- **Synthétise** la voix (Edge TTS — voix neuronales Microsoft, gratuit, sans clé API)
- **Publie** le MP3 + le flux RSS conforme iTunes sur GitHub Pages (URL HTTPS publique)
- **Génère chaque jour** via GitHub Actions (heure de livraison configurable)
- **Dashboard local** pour tout régler : sources, voix (avec extrait écoutable),
  nombre de titres/brèves, heure de livraison, épisodes, QR code d'abonnement

## 🚀 Démarrage rapide

### Prérequis

- Python **3.11+** : `brew install python`
- **ffmpeg** : `brew install ffmpeg`
- **GitHub CLI** connecté : `brew install gh && gh auth login`
- [uv](https://docs.astral.sh/uv/) : `brew install uv`

### Installation + première livraison

```bash
make setup
```

C'est tout. `make setup` :

1. installe les dépendances,
2. crée ton repo GitHub (nom `myop` par défaut — `uv run myop setup --repo mon-nom` pour changer),
3. génère le **premier épisode** et le publie,
4. active GitHub Pages et programme la génération quotidienne,
5. affiche **l'URL de ton flux RSS**.

### S'abonner dans ton lecteur

Copie l'URL du flux (ex. `https://ton-user.github.io/myop/podcast.xml`) :

| Lecteur | Comment s'abonner |
|---|---|
| **Apple Podcasts** (macOS) | Fichier → S'abonner au podcast… → coller l'URL |
| **Apple Podcasts** (iOS) | scanne le QR code du dashboard, ou partage l'URL vers Podcasts |
| **Overcast** | Ajouter par URL |
| **Pocket Casts** | Ajouter un podcast → par URL RSS |

Le QR code est disponible dans le dashboard (onglet Épisodes) et sur la page
GitHub Pages du podcast.

## 🎛 Dashboard local

```bash
make serve   # → http://localhost:8484
```

| Onglet | Actions |
|---|---|
| **Réglages** | titre, description, voix (extrait écoutable), débit, nombre de titres/brèves, heure de livraison |
| **Sources** | ajouter / supprimer / réordonner des flux RSS, tester un flux (aperçu des derniers articles) |
| **Épisodes** | générer maintenant, écouter, publier sur GitHub, déclencher l'action manuellement, QR code |

Après modification des réglages, clique sur **« Publier la config »** pour que la
génération quotidienne (GitHub Actions) en tienne compte.

## 🧰 Commandes

```bash
uv run myop setup              # crée le repo, publie le 1er épisode, active Pages
uv run myop serve              # dashboard local (port 8484)
uv run myop generate           # génère l'épisode du jour
uv run myop generate --publish # génère + publie sur GitHub Pages
uv run myop publish            # publie dist/ sur GitHub Pages
uv run myop trigger            # déclenche la génération distante (GitHub Actions)
uv run myop voices             # liste les voix françaises disponibles
```

## ⚙️ Comment ça marche

- `app/sources.py` — collecte RSS parallèle, filtrage 24 h/48 h, dédoublonnage,
  historisation (`seen.json` sur la branche `gh-pages` pour ne jamais rediffuser)
- `app/script.py` — rédaction déterministe du briefing (aucune IA requise)
- `app/tts.py` — Edge TTS segment par segment + assemblage ffmpeg (pydub)
- `app/feed.py` — flux RSS 2.0 avec tags iTunes (enclosure, guid stable, pochette)
- `app/generate.py` — orchestration : épisode `dist/episodes/AAAA-MM-JJ.mp3` + métadonnées
- `app/publish.py` — publication sur la branche `gh-pages` (accumule les épisodes,
  ne supprime jamais), activation Pages via `gh`
- `app/dashboard.py` — dashboard FastAPI
- `.github/workflows/daily.yml` — cron quotidien (heure = `delivery_hour` de
  `config.yaml`, converti Paris → UTC). Attention : GitHub interprète le cron en
  UTC ; l'heure exacte peut varier d'une heure entre été/hiver.

## 🔧 Personnalisation

Tout est dans `config.yaml` (ou le dashboard). Quelques exemples :

- **Voix** : `fr-FR-HenriNeural` (homme), `fr-FR-VivienneMultilingualNeural`,
  voix québécoises, belges, suisses… (`uv run myop voices` pour la liste)
- **Pochette** : remplace simplement `dist/cover.png` par ta propre image
  1400×1400 et republie (une pochette est générée automatiquement sinon)
- **Heure de livraison** : `delivery_hour: '08:00'` dans `config.yaml`,
  puis `myop setup` ou le dashboard mettent à jour le cron
- **Durée de l'épisode** : joue sur `num_headlines`, `num_briefs`, `max_brief_chars`

## ❓FAQ

**Le MP3 est hébergé où ?** Sur la branche `gh-pages` de ton repo (GitHub Pages).
Les fichiers de moins de 100 Mo sont acceptés ; un épisode de 4 min ≈ 1,5 Mo,
soit des années d'épisodes quotidiens sans souci. Pense à purger la branche si
tu veux repartir de zéro (`git push origin --delete gh-pages`).

**Ça coûte quoi ?** Rien : Edge TTS est gratuit et GitHub Actions + Pages sont
gratuits pour les repos publics. Pour un repo **privé**, les minutes Actions sont
limitées (~2000 min/mois) et Pages nécessite GitHub Pro — l'épisode quotidien
consomme ~5 min/mois.

**Je n'ai rien reçu ce matin.** Vérifie l'exécution du workflow :
`gh run list --workflow daily.yml` puis `gh run watch`. Si les flux n'ont rien
publié de nouveau, aucun épisode n'est créé (`skip_if_empty: true`).

**Rediffusion d'un article ?** `seen.json` (sur gh-pages) mémorise tout ce qui a
été lu ; supprime-le et republie pour réinitialiser.

## 🧪 Tests

```bash
make test   # pytest : config, collecte RSS, script, TTS simulé, flux, cron, pipeline
```
