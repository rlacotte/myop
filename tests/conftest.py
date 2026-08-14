"""Fixtures partagées : show de test, flux RSS simulés, client httpx mocké."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.config import Config, Show, Source


def make_rss(items: list[dict]) -> bytes:
    """Construit un flux RSS minimal à partir d'items {title, link, guid, date, summary}."""
    entries = ""
    for item in items:
        entries += f"""
        <item>
          <title>{item['title']}</title>
          <link>{item['link']}</link>
          <guid>{item.get('guid', item['link'])}</guid>
          <pubDate>{item['date'].strftime('%a, %d %b %Y %H:%M:%S GMT')}</pubDate>
          <description>{item.get('summary', '')}</description>
        </item>"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel>
      <title>Flux de test</title>
      <link>https://example.com</link>
      <description>test</description>
      {entries}
    </channel></rss>""".encode()


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 8, 14, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
def show() -> Show:
    """Émission de test : 2 sources, 5 titres, 2 brèves."""
    return Show(
        id="test",
        title="Podcast Test",
        num_headlines=5,
        num_briefs=2,
        max_per_source=2,
        sources=[
            Source(name="Source A", url="https://a.example/rss"),
            Source(name="Source B", url="https://b.example/rss"),
        ],
    )


@pytest.fixture
def config(show: Show) -> Config:
    return Config(
        shows=[show],
        github={"repo": "me/myop", "pages_base": "https://me.github.io/myop/"},
    )


@pytest.fixture
def rss_a(now: datetime) -> bytes:
    return make_rss(
        [
            {
                "title": "Grosse actu A1",
                "link": "https://a.example/article-1?utm_source=rss",
                "date": now - timedelta(minutes=30),
                "summary": "<p>Premier résumé avec du <b>HTML</b>.</p>",
            },
            {
                "title": "Actu A2",
                "link": "https://a.example/article-2",
                "date": now - timedelta(hours=2),
                "summary": "Résumé article 2.",
            },
            {
                "title": "Vieux A3",
                "link": "https://a.example/article-3",
                "date": now - timedelta(days=5),  # hors fenêtre
            },
        ]
    )


@pytest.fixture
def rss_b(now: datetime) -> bytes:
    return make_rss(
        [
            {
                "title": "Actu B1",
                "link": "https://b.example/article-1",
                "date": now - timedelta(hours=3),
                "summary": "Résumé B1.",
            },
            # Doublon cross-source : même URL (paramètres de tracking en plus)
            {
                "title": "Grosse actu A1 (repris)",
                "link": "https://a.example/article-1",
                "date": now - timedelta(minutes=25),
            },
            {
                "title": "Actu très ancienne B2",
                "link": "https://b.example/article-ancien",
                "date": now - timedelta(days=30),
            },
        ]
    )


@pytest.fixture
def mock_client(rss_a: bytes, rss_b: bytes) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        feeds = {"https://a.example/rss": rss_a, "https://b.example/rss": rss_b}
        body = feeds.get(str(request.url))
        if body is None:
            return httpx.Response(404)
        return httpx.Response(200, content=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))
