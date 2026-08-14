"""CLI MYOP : setup, serve, generate, publish, trigger, voices."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import publish
from .config import CONFIG_PATH, Config, load_config, save_config, write_default_config
from .generate import DIST_DIR, generate_episode
from .script import PARIS

DEFAULT_REPO_NAME = "myop"


def _check_prerequisites(interactive: bool = True) -> list[str]:
    """Vérifie ffmpeg / gh / git ; retourne les problèmes non bloquants."""
    problems: list[str] = []
    if not publish.sh(["ffmpeg", "-version"], check=False):
        problems.append("ffmpeg est introuvable — installe-le : brew install ffmpeg")
    if not publish.sh(["git", "--version"], check=False):
        problems.append("git est introuvable.")
    if not publish.sh(["gh", "auth", "status"], check=False):
        problems.append("gh n'est pas authentifié — lance : gh auth login")
    for problem in problems:
        print(f"  ⚠️  {problem}")
    return problems


def _ensure_git_repo() -> None:
    """git init si le dossier n'est pas encore un repo."""
    if publish.sh(["git", "rev-parse", "--is-inside-work-tree"], check=False) != "true":
        publish.sh(["git", "init", "-b", "main"])


def _initial_commit_if_needed() -> None:
    if publish.sh(["git", "rev-parse", "HEAD"], check=False):
        return
    publish.sh(["git", "add", "-A"])
    publish.sh(["git", "commit", "-m", "MYOP : initialisation du podcast"])


def cmd_setup(args) -> int:
    print("🛠  Configuration de la livraison quotidienne…")
    problems = _check_prerequisites()
    if any("gh" in p for p in problems):
        print("❌ Corrige gh avant de relancer `myop setup`.")
        return 1

    _ensure_git_repo()
    config = write_default_config()

    # Repo GitHub : réutilise l'existant sinon crée
    slug = publish.remote_slug() or config.github.repo
    if not slug:
        name = args.repo or DEFAULT_REPO_NAME
        print(f"   création du repo GitHub « {name} »…")
        _initial_commit_if_needed()
        slug = publish.setup_repo(name, private=args.private)
    config.github.repo = slug
    config.github.pages_base = publish.pages_base_for(slug)
    save_config(config)
    publish.update_workflow_cron(config.delivery_hour)

    _initial_commit_if_needed()
    if not publish.remote_slug():
        publish.setup_repo("", private=False, slug=slug)

    # Premier épisode en direct, publié immédiatement
    print("🎙  Génération du premier épisode (flux RSS + voix)…")
    publish.fetch_existing(DIST_DIR)
    result = asyncio.run(generate_episode(config))
    for warning in result.warnings:
        print(f"  ⚠️  {warning}")
    if not result.ok:
        print(f"❌ Pas d'épisode : {result.reason}")
        print("   Vérifie tes sources RSS (myop serve → onglet Sources).")
        return 1
    print(f"   ✅ {result.episode_path.name} — {result.duration // 60} min {result.duration % 60:02d}s")

    print("📦 Publication sur GitHub Pages…")
    publish.push_config(CONFIG_PATH)
    publish.publish_dist(message=f"épisode {result.episode_id}")

    print("🌐 Activation de GitHub Pages…")
    config.github.pages_base = publish.enable_pages(slug)
    save_config(config)
    publish.push_config(CONFIG_PATH)

    print()
    print("═" * 62)
    print("🎉 Ton podcast est en ligne !")
    print(f"   Flux RSS : {config.feed_url}")
    print(f"   Site     : {config.github.pages_base}")
    print("═" * 62)
    print("📲 Abonne-toi dans ton lecteur de podcast :")
    print("   Apple Podcasts : Fichier → S'abonner au podcast… → colle l'URL")
    print("   Overcast/Pocket Casts : Ajouter par URL / RSS")
    print("   (ou scanne le QR code dans le dashboard : myop serve)")
    print()
    print("☀️  Chaque matin, un nouvel épisode sera généré automatiquement.")
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    from .dashboard import app

    print(f"🎛  Dashboard MYOP → http://localhost:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def cmd_generate(args) -> int:
    config = load_config()
    now = None
    if args.date:
        local = datetime.now(tz=PARIS)
        try:
            day = datetime.strptime(args.date, "%Y-%m-%d")
        except ValueError:
            print(f"❌ Date invalide : {args.date} (format attendu AAAA-MM-JJ)")
            return 1
        now = local.replace(year=day.year, month=day.month, day=day.day)
    if args.publish:
        publish.fetch_existing(DIST_DIR)
    result = asyncio.run(generate_episode(config, now=now))
    for warning in result.warnings:
        print(f"⚠️  {warning}")
    if not result.ok:
        print(f"ℹ️  Aucun épisode généré : {result.reason}")
        return 0 if config.skip_if_empty else 1
    print(f"✅ Épisode {result.episode_id} : {result.episode_path}")
    print(f"   {result.duration // 60} min {result.duration % 60:02d}s — {result.size // 1024} Ko")
    for title in result.titles:
        print(f"   • {title}")
    if args.publish:
        publish.publish_dist(message=f"épisode {result.episode_id}")
        print(f"📦 Publié → {config.feed_url}")
    return 0


def cmd_publish(args) -> int:
    publish.publish_dist(message="publication manuelle")
    print(f"📦 Publié → {load_config().feed_url}")
    return 0


def cmd_trigger(args) -> int:
    publish.trigger_workflow()
    print("🚀 Workflow déclenché — suis l'exécution :")
    print("   gh run watch")
    return 0


def cmd_voices(args) -> int:
    from .tts import list_voices

    for voice in asyncio.run(list_voices()):
        marker = " ← actuelle" if voice["ShortName"] == args.current else ""
        print(f"  {voice['ShortName']:44s} {voice['Gender']:8s}{marker}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="myop",
        description="MYOP — My Own Podcast : ton briefing quotidien sur ton lecteur de podcast",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    setup = sub.add_parser("setup", help="crée le repo GitHub, publie le 1er épisode, active Pages")
    setup.add_argument("--repo", help="nom du repo GitHub (défaut : myop)")
    setup.add_argument("--private", action="store_true", help="repo privé (Pages public limité)")
    setup.set_defaults(func=cmd_setup)

    serve = sub.add_parser("serve", help="ouvre le dashboard de configuration")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8484)
    serve.set_defaults(func=cmd_serve)

    generate = sub.add_parser("generate", help="génère l'épisode du jour")
    generate.add_argument("--publish", action="store_true", help="publie sur gh-pages ensuite")
    generate.add_argument("--date", help="date de l'épisode (AAAA-MM-JJ, pour test)")
    generate.set_defaults(func=cmd_generate)

    publish_cmd = sub.add_parser("publish", help="publie dist/ sur gh-pages")
    publish_cmd.set_defaults(func=cmd_publish)

    trigger = sub.add_parser("trigger", help="déclenche le workflow GitHub Actions")
    trigger.set_defaults(func=cmd_trigger)

    voices = sub.add_parser("voices", help="liste les voix françaises disponibles")
    voices.add_argument("--current", help="voix actuellement configurée (marquage)")
    voices.set_defaults(func=cmd_voices)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except RuntimeError as exc:
        print(f"❌ {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
