"""Point d'entrée Vercel : sert le dashboard MYOP en fonction serverless.

Le mode distant s'active tout seul (variable VERCEL) : la config est lue dans
le dépôt GitHub, l'état dans /tmp, et tout ce qui fabrique de l'audio est
refusé avec un message explicite — cela reste le travail de GitHub Actions.
"""

import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

# La fonction s'exécute depuis api/ : la racine du dépôt doit être importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.dashboard import app as dashboard  # noqa: E402

PATH_PARAM = "__myop_path"


class VercelPath:
    """Restaure le chemin demandé, que la réécriture Vercel écrase.

    Vercel dirige toutes les URL vers cette fonction et lui présente
    « /api/index » ; le chemin d'origine n'apparaît dans aucun en-tête. On le
    fait donc voyager en paramètre (voir vercel.json) et on le replace dans le
    scope ASGI avant que FastAPI ne cherche sa route.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            params = parse_qsl(scope.get("query_string", b"").decode(), keep_blank_values=True)
            original = next((value for key, value in params if key == PATH_PARAM), None)
            if original is not None:
                path = original or "/"
                scope = {
                    **scope,
                    "path": path,
                    "raw_path": path.encode(),
                    "query_string": urlencode(
                        [(k, v) for k, v in params if k != PATH_PARAM]
                    ).encode(),
                }
        await self.app(scope, receive, send)


app = VercelPath(dashboard)
