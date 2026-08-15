# 🎙️ MYOP — My Own Podcast

**Ta radio personnelle, générée chaque jour et livrée automatiquement sur ton lecteur de podcast.**

MYOP collecte les flux RSS que tu choisis, rédige un briefing (par IA ou de façon
déterministe), le fait lire par une voix de synthèse, et publie l'épisode sur un
flux RSS conforme iTunes. Tu t'abonnes **une seule fois** dans Apple Podcasts,
Overcast ou Pocket Casts — et tu reçois tes émissions chaque jour, à l'heure
que tu as choisie.

```
Tes flux RSS ──► sélection intelligente ──► script (IA) ──► voix + jingle ──► MP3 chapitré
                                                                                │
Toi ◄── Apple Podcasts / Overcast / page web ◄── flux RSS (GitHub Pages) ◄── GitHub Actions (horaire)
```

## ✨ Tout ce que MYOP sait faire

### 🎙️ Émissions
- **Multi-émissions** : un briefing le matin, un magazine tech le soir, un flash
  sport le week-end… chacune avec ses sources, sa voix, son heure et **son flux RSS**
- **Segments riches** : météo du jour (Open-Meteo, gratuit) et éphéméride
  (jours fériés, pleine lune) intégrés au script
- **Liste de lecture** : colle l'URL d'un article, MYOP l'extrait et le fait lire
  dans le prochain épisode — écoute ta pile d'articles
- **Dialogue à deux voix** : ajoute une 2ᵉ voix, l'IA écrit un duo radio
- **Boucle de goût** : vote 👍/👎 sur les brèves — les sources appréciées
  remontent, les sujets rejetés disparaissent

### ✍️ Rédaction
- **Script par IA** (OpenRouter — Gemini par défaut) avec **persona éditable** :
  ton radio, humour, personnage…
- **Traduction automatique** : sources en anglais, espagnol… résumées en français
- **Éditeur de script** : prépare l'épisode, relis et retouche le texte
  (ou réécris-le) avant la synthèse vocale
- **Repli déterministe garanti** : si l'IA est indisponible, l'épisode part quand même

### 🎧 Audio
- **Voix Edge TTS** (gratuit, ~8 voix françaises) ou **ElevenLabs** (premium)
- **Jingle d'intro/outro et transitions** — 100 % synthétisés, aucun fichier à fournir
- **Chapitrage ID3** : Intro · Titres · Météo · Brève 1… navigables dans le lecteur
- **Transcription** : texte lisible depuis la page publique et WebVTT calé sur
  l'audio, annoncé aux lecteurs qui gèrent `<podcast:transcript>`

### 📡 Sources
- **Bibliothèque intégrée** : 44 flux vérifiés en 12 catégories (généralistes,
  politique, international, éco, tech, sciences, culture, sport, environnement,
  santé, crypto, presse internationale traduite)
- **Activation par flux ou par catégorie** en un clic, recherche, test en direct
- **Santé des sources** : diagnostic en parallèle (items, fraîcheur, latence)
- **Import/export OPML** depuis tes lecteurs RSS existants
- **Sélection intelligente** : fraîcheur d'abord, puis goût (👍/👎) et présence
  d'un vrai résumé — chacun pesant quelques heures de fraîcheur, jamais plus
- **Dédoublonnage** par URL, par similarité de titres entre sources, **et sur
  les jours précédents** : un sujet déjà diffusé ne revient pas de 3 jours,
  même repris ailleurs sous un autre titre

### 🌍 Diffusion
- **Page publique** : abonnement **one-tap** (Apple Podcasts, Overcast, Pocket
  Casts), QR code et **lecteur web** pour écouter sans s'abonner
- **Un flux RSS par émission**, conformes iTunes (enclosure, guid, pochette auto)
- **GitHub Actions** : la planification est générée depuis tes heures de
  livraison (deux crons par heure, été et hiver — un épisode part à l'heure
  juste toute l'année, sans réveiller le runner 24 fois par jour)
- **Panne signalée** : si la génération échoue, une issue GitHub s'ouvre
  (et se commente aux échecs suivants) avec le lien du journal
- **Rétention** : les épisodes au-delà des N derniers (60 par défaut) sortent
  du flux et du site — GitHub Pages plafonne à 1 Go
- **Rattrapage** : régénère n'importe quelle date passée
- Statistiques optionnelles (GoatCounter, respectueux de la vie privée)

## 🚀 Démarrage rapide

### Prérequis

- Python **3.11+**, **ffmpeg**, **GitHub CLI** connecté :
  ```bash
  brew install python ffmpeg gh && gh auth login
  ```
- [uv](https://docs.astral.sh/uv/) : `brew install uv`

### Installation + mise en ligne (une commande)

```bash
make setup
```

`myop setup` crée le repo GitHub, génère et publie le premier épisode, active
GitHub Pages et affiche l'URL de ton flux. Bilan de santé à tout moment :

```bash
uv run myop doctor   🩺 vérifie tout : outils, clé IA, repo, flux, sources
```

### S'abonner

Ouvre la page publique de ton podcast (ex. `https://ton-user.github.io/myop/`) :
boutons one-tap, QR code à scanner depuis le téléphone, ou lecteur web.

## 🎛 Le dashboard

```bash
make serve   # → http://localhost:8484
```

| Onglet | Actions |
|---|---|
| **Réglages** | par émission : titre, heure, voix (+ extrait écoutable, 2ᵉ voix, météo, éphéméride, volume de titres) · globaux : persona IA, jingle, chapitrage, rétention des épisodes |
| **Sources** | bibliothèque 12 catégories (switch par flux, « tout activer » par catégorie, recherche), santé en direct, OPML, flux perso |
| **Épisodes & script** | générer, **préparer/éditer le script** puis synthétiser, liste de lecture, votes 👍/👎, rattrapage par date, publication GitHub, QR code |

## 🧰 Commandes

```bash
uv run myop setup                # crée le repo, publie, active Pages
uv run myop serve                # dashboard local (port 8484)
uv run myop generate             # génère toutes les émissions maintenant
uv run myop generate --show soir # une seule émission
uv run myop generate --fresh     # ignore l'historique (régénère)
uv run myop generate --date 2026-08-14   # rattrapage
uv run myop publish              # publie dist/ sur GitHub Pages
uv run myop trigger              # déclenche le workflow distant
uv run myop voices               # voix françaises disponibles
uv run myop doctor               # bilan santé complet
```

## ⚙️ Architecture

```
app/
├── config.py     # émissions (shows) + réglages partagés, migration auto v1→v2
├── library.py    # bibliothèque de 44 flux vérifiés en 12 catégories
├── sources.py    # collecte RSS : fenêtre 24/48 h, dédoublonnage URL + titres, diversité
├── weather.py    # météo Open-Meteo (gratuit, sans clé)
├── ephemeris.py  # jours fériés (computus), phases de lune — 100 % hors ligne
├── reading.py    # liste de lecture : extraction d'articles, file d'attente
├── feedback.py   # boucle de goût : scores de sources, mots-clés détestés
├── script.py     # script déterministe (repli garanti)
├── ai.py         # rédaction IA : persona, dialogue, contexte, traduction
├── jingle.py     # jingle + transitions synthétisés (oscillateurs)
├── tts.py        # voix Edge / ElevenLabs, assemblage, bornes de chapitres
├── chapters.py   # chapitrage ID3 (CHAP/CTOC via mutagen)
├── generate.py   # pipeline : collecte → script → audio → flux par émission
├── feed.py       # flux RSS iTunes par show + page publique one-tap/lecteur
├── publish.py    # gh-pages (accumulation), Pages, secrets
└── dashboard.py  # interface locale complète
```

## ❓FAQ

**Combien ça coûte ?** Rien en configuration par défaut : Edge TTS gratuit,
GitHub Actions + Pages gratuits (repo public). L'IA via OpenRouter coûte quelques
centimes par épisode (Gemini Flash) ; ElevenLabs en option est payant.

**Pourquoi l'IA dans le cloud alors que la clé est locale ?** Ajoute le secret
`OPENROUTER_API_KEY` au repo GitHub — le workflow l'exporte déjà.

**Il n'y a pas eu d'épisode ce matin.** Une issue GitHub étiquetée `myop-panne`
a dû s'ouvrir avec le lien du journal. Sinon `gh run list --workflow daily.yml`
puis `gh run watch`, et la santé des sources (`myop doctor` ou dashboard).

**Même info répétée ?** Le dédoublonnage joue entre sources et sur les 3 jours
précédents. Il reste volontairement prudent (mêmes mots significatifs exigés) :
un rebondissement réel sur un sujet en cours repasse, ce qui est voulu.

**Changer l'heure de livraison ?** Dashboard (Réglages) ou `delivery_hour` dans
`config.yaml`, puis « Publier la config » : la planification du workflow est
régénérée à partir de tes heures (été et hiver).

**Réinitialiser la mémoire des articles déjà diffusés ?** Supprime `seen-<show>.json`
de la branche gh-pages, ou régénère avec `--fresh`.

## 🧪 Tests

```bash
make test   # 67 tests : config, collecte, script, IA, audio, chapitres, flux, dashboard
```
