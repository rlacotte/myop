"""CLI MYOP : setup, serve, generate, publish, trigger, voices, doctor."""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from . import publish
from .config import CONFIG_PATH, write_default_config, load_config, save_config
from .generate import DIST_DIR, generate_episode
from .script import PARIS

DEFAULT_REPO_NAME = "myop"


def _tool_ok(cmd: list[str]) -> bool:
    """Vrai si la commande réussit (gh auth status écrit sur stderr, pas stdout)."""
    return subprocess.run(cmd, capture_output=True).returncode == 0


def _check_prerequisites(interactive: bool = True) -> list[str]:
    """Vérifie ffmpeg / gh / git ; retourne les problèmes non bloquants."""
    problems: list[str] = []
    if not _tool_ok(["ffmpeg", "-version"]):
        problems.append("ffmpeg est introuvable — installe-le : brew install ffmpeg")
    if not _tool_ok(["git", "--version"]):
        problems.append("git est introuvable.")
    if not _tool_ok(["gh", "auth", "status"]):
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


def _shows_due(config, *, now=None, show_id=None, all_shows=False, due_only=False):
    """Émissions à générer : une précise, toutes, ou seulement celles dues maintenant.

    Sans filtre (interactif), on génère tout : c'est ce qu'attend un humain.
    Le cron horaire passe --due : seules les émissions de l'heure partent.
    """
    now = now or datetime.now(tz=PARIS)
    if show_id:
        return [config.show(show_id)]
    if due_only and not all_shows:
        hour = now.astimezone(PARIS).strftime("%H")
        return [
            s for s in config.shows
            if s.enabled and s.delivery_hour.split(":")[0] == hour
        ]
    return [s for s in config.shows if s.enabled]


def cmd_setup(args) -> int:
    print("🛠  Configuration de la livraison quotidienne…")
    problems = _check_prerequisites()
    if any("gh" in p for p in problems):
        print("❌ Corrige gh avant de relancer `myop setup`.")
        return 1

    _ensure_git_repo()
    config = write_default_config()
    show = config.show()

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

    _initial_commit_if_needed()
    if not publish.remote_slug():
        publish.setup_repo("", private=False, slug=slug)

    # Premier épisode en direct, publié immédiatement
    print(f"🎙  Génération du premier épisode de « {show.title} »…")
    publish.fetch_existing(DIST_DIR)
    result = asyncio.run(generate_episode(config, show))
    for warning in result.warnings:
        print(f"  ⚠️  {warning}")
    if not result.ok:
        # Pas de nouvel article mais un épisode local existe déjà ? On le publie.
        if any((DIST_DIR / "episodes").glob("*/*.json")):
            print("   ℹ️  Pas de nouvel article — publication de l'épisode existant.")
        else:
            print(f"❌ Pas d'épisode : {result.reason}")
            print("   Vérifie tes sources RSS (myop serve → onglet Sources).")
            return 1
    else:
        _print_result(result, config)

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
    print(f"   Site     : {config.github.pages_base}")
    for s in config.shows:
        if s.enabled:
            print(f"   Flux     : {config.feed_url(s)}  ({s.title})")
    print("═" * 62)
    print("📲 Abonne-toi depuis la page publique (QR code + boutons one-tap),")
    print("   ou colle l'URL du flux dans Apple Podcasts / Overcast / Pocket Casts.")
    print()
    print("☀️  Chaque jour à l'heure choisie, un nouvel épisode sera généré.")
    return 0


def _print_result(result, config) -> None:
    print(f"   ✅ {result.episode_path.name} — {result.duration // 60} min {result.duration % 60:02d}s")
    if result.ai_used:
        print(f"   ✍️  script rédigé par l'IA ({config.ai.model})")
    if result.chapter_titles:
        print(f"   🔖 chapitres : {' · '.join(result.chapter_titles)}")
    if result.reading_count:
        print(f"   📖 {result.reading_count} article(s) de la liste de lecture")
    for title in result.titles:
        print(f"   • {title}")


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

    exit_code = 0
    shows = _shows_due(config, now=now, show_id=args.show, all_shows=args.all, due_only=args.due)
    if not shows:
        print("ℹ️  Aucune émission due à cette heure (livraison programmée plus tard).")
        return 0
    for show in shows:
        print(f"🎙  {show.title} ({show.id}) — {show.delivery_hour}")
        result = asyncio.run(
            generate_episode(config, show, now=now, ignore_seen=args.fresh)
        )
        for warning in result.warnings:
            print(f"   ⚠️  {warning}")
        if not result.ok:
            print(f"   ℹ️  Aucun épisode : {result.reason}")
            exit_code = exit_code or (0 if config.skip_if_empty else 1)
            continue
        _print_result(result, config)
        if args.publish:
            publish.publish_dist(message=f"épisode {show.id}/{result.episode_id}")
            print(f"   📦 Publié → {config.feed_url(show)}")
    return exit_code


def cmd_publish(args) -> int:
    publish.publish_dist(message="publication manuelle")
    config = load_config()
    for show in config.shows:
        if show.enabled:
            print(f"📦 {show.title} → {config.feed_url(show)}")
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


def cmd_doctor(args) -> int:
    """Bilan de santé complet de l'installation."""
    print("🩺  MYOP doctor — bilan de l'installation\n")
    ok = True

    checks = [
        ("Python ≥ 3.11", sys.version_info >= (3, 11), "python3 --version"),
        ("ffmpeg (audio)", _tool_ok(["ffmpeg", "-version"]), "brew install ffmpeg"),
        ("git", _tool_ok(["git", "--version"]), "brew install git"),
        ("gh + authentifié", _tool_ok(["gh", "auth", "status"]), "brew install gh && gh auth login"),
    ]
    for name, passed, fix in checks:
        print(f"  {'✅' if passed else '❌'} {name}" + ("" if passed else f"  → {fix}"))
        ok = ok and passed

    config = load_config()
    from .ai import load_api_key

    ai_key = load_api_key(config)
    print(f"  {'✅' if config.ai.enabled else 'ℹ️ '} IA ({config.ai.model})"
          + (" — clé présente" if ai_key else " — clé absente (repli déterministe)" if config.ai.enabled else " (désactivée)"))

    repo = publish.remote_slug()
    print(f"  {'✅' if repo else 'ℹ️ '} Repo GitHub : {repo or 'pas encore créé (myop setup)'}")
    if repo and config.github.pages_base:
        print(f"  ✅ Pages : {config.github.pages_base}")

    print(f"\n  🎙  {len(config.shows)} émission(s) :")
    for show in config.shows:
        status = "activée" if show.enabled else "en pause"
        print(f"     • {show.title} ({show.id}) — {show.delivery_hour}, "
              f"{len(show.sources)} sources, {status}")

    print("\n  📡 Santé des sources (test en direct)…")
    import httpx

    async def _health():
        results = []
        async with httpx.AsyncClient(
            headers={"User-Agent": "Mozilla/5.0 myop/0.1"}, timeout=12, follow_redirects=True
        ) as client:
            import feedparser

            async def one(source):
                try:
                    resp = await client.get(source.url)
                    resp.raise_for_status()
                    entries = feedparser.parse(resp.content).entries
                    return source.name, len(entries), None
                except Exception as exc:
                    return source.name, 0, exc.__class__.__name__

            show = config.show()
            results = await asyncio.gather(*[one(s) for s in show.sources])
        return results

    for name, count, error in asyncio.run(_health()):
        if error:
            print(f"     ❌ {name} — {error}")
        else:
            print(f"     ✅ {name} — {count} items")

    print("\n" + ("✅ Tout est prêt." if ok else "⚠️  Corrige les points ❌ puis relance."))
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="myop",
        description="MYOP — My Own Podcast : ta radio personnelle, chaque jour sur ton lecteur",
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

    generate = sub.add_parser("generate", help="génère les épisodes du jour")
    generate.add_argument("--publish", action="store_true", help="publie sur gh-pages ensuite")
    generate.add_argument("--date", help="date de l'épisode (AAAA-MM-JJ, rattrapage)")
    generate.add_argument("--fresh", action="store_true", help="ignore l'historique (régénère)")
    generate.add_argument("--show", help="une seule émission (id)")
    generate.add_argument("--all", action="store_true", help="toutes les émissions (défaut interactif)")
    generate.add_argument("--due", action="store_true", help="seulement les émissions dues à cette heure (mode cron)")
    generate.set_defaults(func=cmd_generate)

    publish_cmd = sub.add_parser("publish", help="publie dist/ sur gh-pages")
    publish_cmd.set_defaults(func=cmd_publish)

    trigger = sub.add_parser("trigger", help="déclenche le workflow GitHub Actions")
    trigger.set_defaults(func=cmd_trigger)

    voices = sub.add_parser("voices", help="liste les voix françaises disponibles")
    voices.add_argument("--current", help="voix actuellement configurée (marquage)")
    voices.set_defaults(func=cmd_voices)

    doctor = sub.add_parser("doctor", help="bilan de santé complet de l'installation")
    doctor.set_defaults(func=cmd_doctor)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except (RuntimeError, KeyError) as exc:
        print(f"❌ {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
