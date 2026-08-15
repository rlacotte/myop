"""Publication GitHub : repo, Pages, branche gh-pages, workflow.

Fonctionne à l'identique en local (identifiants git/gh de l'utilisateur)
et dans GitHub Actions (GITHUB_TOKEN persisté par actions/checkout).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "daily.yml"
PUBLISH_DIR = ROOT / ".publish"


def sh(cmd: list[str], cwd: Path | None = None, check: bool = True) -> str:
    """Exécute une commande, retourne sa sortie ( échec → CalledProcessError )."""
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"Échec : {' '.join(cmd)}\n{proc.stdout.strip()}\n{proc.stderr.strip()}"
        )
    return proc.stdout.strip()


# ---------------------------------------------------------------- livraison --

def cron_for(delivery_hour: str, *, now: datetime | None = None) -> str:
    """Convertit une heure Paris (« 07:30 ») en cron UTC « 30 5 * * * »."""
    now = now or datetime.now(tz=PARIS)
    hh, mm = (int(part) for part in delivery_hour.split(":"))
    paris_time = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    utc_time = paris_time.astimezone(timezone.utc)
    return f"{utc_time.minute} {utc_time.hour} * * *"


def crons_for(config, *, reference: datetime | None = None) -> list[str]:
    """Crons UTC couvrant les heures de livraison, heure d'été comme heure d'hiver.

    GitHub Actions ne planifie qu'en UTC : une émission de 7h30 à Paris tombe
    à 5h30 UTC l'été et 6h30 l'hiver. On déclare les deux, et `myop generate
    --due` (qui raisonne en heure de Paris) ignore le déclenchement hors saison.

    Sans cela, la seule façon d'être juste toute l'année était un cron horaire,
    soit 24 exécutions par jour dont 23 sans rien à produire.
    """
    reference = reference or datetime.now(tz=PARIS)
    seasons = [
        reference.replace(month=7, day=1),  # UTC+2
        reference.replace(month=1, day=15),  # UTC+1
    ]
    hours = {s.delivery_hour for s in config.shows if s.enabled}
    crons = {cron_for(hour, now=season) for hour in hours for season in seasons}
    return sorted(crons, key=lambda c: [int(part) for part in c.split()[:2][::-1]])


# Bloc de lignes « - cron: "…" » consécutives dans le workflow
_CRON_BLOCK = re.compile(r'( *)- cron: "[^"]*"\n(?:\s*- cron: "[^"]*"\n)*')


def update_workflow_schedule(config, path: Path = WORKFLOW_PATH) -> list[str]:
    """Réécrit la planification du workflow d'après les heures de livraison."""
    crons = crons_for(config)
    if not crons or not path.exists():
        return []
    content = path.read_text(encoding="utf-8")
    match = _CRON_BLOCK.search(content)
    if not match:
        return []
    indent = match.group(1)
    block = "".join(f'{indent}- cron: "{cron}"\n' for cron in crons)
    if block != match.group(0):
        path.write_text(content[: match.start()] + block + content[match.end():], encoding="utf-8")
    return crons


def fetch_existing(dist_dir: Path) -> None:
    """Récupère les métadonnées d'épisodes et l'historique publiés sur gh-pages.

    Permet de reconstruire des flux complets (tous les épisodes) et d'éviter
    de rediffuser des articles déjà traités les jours précédents.
    """
    import json

    try:
        sh(["git", "fetch", "origin", "gh-pages", "--depth=1"])
    except RuntimeError:
        return  # branche pas encore publiée : premier épisode

    listing = sh(["git", "ls-tree", "-r", "--name-only", "FETCH_HEAD"])
    for blob in listing.splitlines():
        if blob.startswith("episodes/") and blob.endswith(".json"):
            target = dist_dir / blob
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(sh(["git", "show", f"FETCH_HEAD:{blob}"]), encoding="utf-8")
        elif blob == "seen.json":
            # Ancien format mono-émission → show « matin »
            _merge_key_set(dist_dir / "seen-matin.json", sh(["git", "show", "FETCH_HEAD:seen.json"]))
        elif blob.startswith(("seen-", "topics-")) and blob.endswith(".json"):
            _merge_key_set(dist_dir / blob, sh(["git", "show", f"FETCH_HEAD:{blob}"]))
        elif blob in ("reading.json", "feedback.json"):
            target = dist_dir / blob
            if not target.exists():  # le local prime (file d'attente / votes récents)
                target.write_text(sh(["git", "show", f"FETCH_HEAD:{blob}"]), encoding="utf-8")


def _merge_key_set(local_file: Path, remote_content: str) -> None:
    """Fusionne un historique distant avec le fichier local (union des clés)."""
    import json

    try:
        remote = set(json.loads(remote_content))
    except json.JSONDecodeError:
        remote = set()
    local = set()
    if local_file.exists():
        try:
            local = set(json.loads(local_file.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            local = set()
    local_file.parent.mkdir(parents=True, exist_ok=True)
    local_file.write_text(json.dumps(sorted(remote | local), ensure_ascii=False), encoding="utf-8")


def prune_published_episodes(dist_dir: Path, worktree: Path, keep: int) -> list[str]:
    """Supprime de gh-pages les épisodes plus anciens que ceux gardés en local.

    Prudence volontaire : tant que le local ne contient pas `keep` épisodes
    d'une émission, on ne touche à rien. Une publication faite sans avoir
    récupéré l'historique distant ne peut donc pas vider le site.
    """
    removed: list[str] = []
    local_root = dist_dir / "episodes"
    if keep <= 0 or not local_root.exists():
        return removed
    for show_dir in sorted(local_root.iterdir()):
        if not show_dir.is_dir():
            continue
        kept = sorted(path.stem for path in show_dir.glob("*.json"))
        if len(kept) < keep:
            continue
        oldest_kept = kept[0]
        published = worktree / "episodes" / show_dir.name
        if not published.exists():
            continue
        for path in sorted(published.iterdir()):
            if path.is_file() and path.stem < oldest_kept:
                path.unlink()
                removed.append(f"{show_dir.name}/{path.name}")
    return removed


def publish_dist(
    dist_dir: Path | None = None,
    message: str = "nouvel épisode",
    *,
    keep_episodes: int | None = None,
) -> None:
    """Publie le contenu de dist/ sur la branche gh-pages.

    Les épisodes déjà en ligne sont conservés, à l'exception de ceux que la
    rétention (config `publishing.keep_episodes`) fait sortir du flux.
    """
    dist_dir = dist_dir or ROOT / "dist"
    if not dist_dir.exists():
        raise RuntimeError("Rien à publier : dist/ est absent.")
    if keep_episodes is None:
        from .config import load_config

        keep_episodes = load_config().publishing.keep_episodes

    if PUBLISH_DIR.exists():
        sh(["git", "worktree", "remove", "--force", str(PUBLISH_DIR)])

    has_remote_branch = bool(sh(["git", "ls-remote", "--heads", "origin", "gh-pages"]))
    if has_remote_branch:
        sh(["git", "fetch", "origin", "gh-pages"])
        sh(["git", "worktree", "add", "--detach", str(PUBLISH_DIR), "origin/gh-pages"])
    else:
        # Premier déploiement : branche orpheline vide
        sh(["git", "worktree", "add", "--detach", str(PUBLISH_DIR)])
        sh(["git", "checkout", "--orphan", "gh-pages"], cwd=PUBLISH_DIR)
        sh(["git", "rm", "-rf", "."], cwd=PUBLISH_DIR, check=False)
        sh(["git", "clean", "-xfd"], cwd=PUBLISH_DIR)

    # Copie du contenu généré (les anciens épisodes présents sur gh-pages sont conservés)
    for item in dist_dir.iterdir():
        target = PUBLISH_DIR / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)

    removed = prune_published_episodes(dist_dir, PUBLISH_DIR, keep_episodes)
    if removed:
        print(f"   🧹 {len(removed)} épisode(s) retiré(s) du site (rétention : {keep_episodes})")

    sh(["git", "add", "-A"], cwd=PUBLISH_DIR)
    status = sh(["git", "status", "--porcelain"], cwd=PUBLISH_DIR)
    if status:
        sh(["git", "commit", "-m", message], cwd=PUBLISH_DIR)
        sh(["git", "push", "origin", "HEAD:gh-pages"], cwd=PUBLISH_DIR)
    sh(["git", "worktree", "remove", "--force", str(PUBLISH_DIR)])


# ------------------------------------------------------------------- GitHub --

def remote_slug() -> str | None:
    """« owner/repo » depuis l'remote origin (None si pas de repo GitHub)."""
    url = sh(["git", "remote", "get-url", "origin"], check=False)
    if not url:
        return None
    match = re.search(r"github\.com[/:]([^/]+)/([^/.]+)(?:\.git)?$", url)
    if match:
        return f"{match.group(1)}/{match.group(2)}"
    try:  # dernier recours : gh connaît le repo
        return sh(["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"])
    except RuntimeError:
        return None


def pages_base_for(slug: str) -> str:
    """URL racine GitHub Pages attendue pour ce repo."""
    owner, repo = slug.split("/")
    if repo.lower() == f"{owner.lower()}.github.io":
        return f"https://{owner}.github.io/"
    return f"https://{owner}.github.io/{repo}/"


def current_branch() -> str:
    return sh(["git", "rev-parse", "--abbrev-ref", "HEAD"])


def push_config(config_path: Path) -> None:
    """Committe config + workflow + assets et pousse la branche courante.

    La planification du workflow est régénérée au passage : le cron poussé
    correspond toujours aux heures de livraison enregistrées.
    """
    from .config import load_config

    update_workflow_schedule(load_config(config_path))
    files = [str(config_path), str(WORKFLOW_PATH)]
    assets = ROOT / "assets"
    if assets.exists():
        files.append(str(assets))
    sh(["git", "add", *files])
    status = sh(["git", "status", "--porcelain"])
    if status:
        sh(["git", "commit", "-m", "réglages : mise à jour du podcast"])
        sh(["git", "push", "origin", current_branch()])


def setup_repo(name: str, *, private: bool, slug: str | None = None) -> str:
    """Crée le repo GitHub (si besoin) et pousse le code. Retourne « owner/repo »."""
    if not slug:
        visibility = "--private" if private else "--public"
        sh(["gh", "repo", "create", name, visibility, "--source", ".", "--push"])
    slug = slug or remote_slug()
    if not slug:
        raise RuntimeError("Impossible de déterminer le repo GitHub.")
    sh(["git", "push", "-u", "origin", current_branch()], check=False)
    return slug


def enable_pages(slug: str) -> str:
    """Active GitHub Pages sur la branche gh-pages. Retourne l'URL du site."""
    # On se fie au code retour : selon la version de gh, l'erreur 404 arrive
    # sur stdout ou stderr — le contenu n'est pas fiable.
    import subprocess

    probe = subprocess.run(
        ["gh", "api", f"repos/{slug}/pages"], capture_output=True, text=True
    )
    if probe.returncode != 0:
        # Pas encore de site Pages : création sur la branche gh-pages
        sh(
            ["gh", "api", "-X", "POST", f"repos/{slug}/pages",
             "-f", "source[branch]=gh-pages", "-f", "source[path]=/"]
        )
        return pages_base_for(slug)

    if "gh-pages" in probe.stdout:
        return pages_base_for(slug)
    # Pages activé sur autre chose : on le repositionne sur gh-pages
    sh(
        ["gh", "api", "-X", "PUT", f"repos/{slug}/pages",
         "-f", "source[branch]=gh-pages", "-f", "source[path]=/"]
    )
    return pages_base_for(slug)


def trigger_workflow() -> None:
    """Déclenche manuellement la génération quotidienne (workflow_dispatch)."""
    sh(["gh", "workflow", "run", "daily.yml"])
