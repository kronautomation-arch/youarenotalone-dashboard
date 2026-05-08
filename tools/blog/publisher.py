"""
Publica blogs en Shopify a partir de archivos JSON en blogs/.

Cada blog tiene 2 archivos:
- blogs/YYYYMMDD-slug.json     → metadata (título, handle, tags, meta SEO, etc.)
- blogs/YYYYMMDD-slug.body.html → cuerpo HTML del artículo

Uso:
    python -m tools.blog.publisher --file blogs/20260508-ropa-ecologica-mujer.json
    python -m tools.blog.publisher --next  # publica el siguiente sin publicar
    python -m tools.blog.publisher --all   # publica todos los pendientes

Requiere SHOPIFY_STORE y SHOPIFY_ACCESS_TOKEN en .env.
El blog destino se identifica por SHOPIFY_BLOG_ID (default: blog "Noticias").
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tools.core.env_loader import load_env, get_env
from tools.core.logger import setup_logger


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BLOGS_DIR = REPO_ROOT / "blogs"
DEFAULT_BLOG_ID = 123541225846  # blog "Noticias" en Yana Shopify
API_VERSION = "2025-07"


class ShopifyBlogClient:
    def __init__(self, shop: str, access_token: str, blog_id: int):
        self.base_url = f"https://{shop}.myshopify.com/admin/api/{API_VERSION}"
        self.blog_id = blog_id
        self.session = requests.Session()
        self.session.headers.update({
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json",
        })

    def list_articles(self) -> list[dict]:
        url = f"{self.base_url}/blogs/{self.blog_id}/articles.json"
        r = self.session.get(url, params={"limit": 250, "fields": "id,handle,title,published_at"}, timeout=30)
        r.raise_for_status()
        return r.json().get("articles", [])

    def find_by_handle(self, handle: str) -> dict | None:
        for a in self.list_articles():
            if a.get("handle") == handle:
                return a
        return None

    def create_article(self, payload: dict) -> dict:
        url = f"{self.base_url}/blogs/{self.blog_id}/articles.json"
        r = self.session.post(url, json={"article": payload}, timeout=30)
        if not r.ok:
            raise RuntimeError(f"Shopify {r.status_code}: {r.text[:500]}")
        return r.json()["article"]

    def update_article(self, article_id: int, payload: dict) -> dict:
        url = f"{self.base_url}/blogs/{self.blog_id}/articles/{article_id}.json"
        r = self.session.put(url, json={"article": payload}, timeout=30)
        if not r.ok:
            raise RuntimeError(f"Shopify {r.status_code}: {r.text[:500]}")
        return r.json()["article"]

    def upsert_metafield(self, article_id: int, namespace: str, key: str, value: str) -> None:
        url = f"{self.base_url}/articles/{article_id}/metafields.json"
        payload = {
            "metafield": {
                "namespace": namespace,
                "key": key,
                "value": value,
                "type": "single_line_text_field",
            }
        }
        r = self.session.post(url, json=payload, timeout=30)
        if not r.ok and r.status_code != 422:
            # 422 puede significar que ya existe. Buscar y actualizar.
            existing_url = f"{self.base_url}/articles/{article_id}/metafields.json"
            existing = self.session.get(existing_url, params={"namespace": namespace, "key": key}, timeout=30).json()
            metas = existing.get("metafields", [])
            if metas:
                mf_id = metas[0]["id"]
                upd_url = f"{self.base_url}/metafields/{mf_id}.json"
                self.session.put(upd_url, json={"metafield": {"id": mf_id, "value": value, "type": "single_line_text_field"}}, timeout=30)


def load_blog(json_path: Path) -> tuple[dict, str]:
    """Lee el JSON + el body HTML asociado."""
    meta = json.loads(json_path.read_text(encoding="utf-8"))
    body_path_relative = meta.get("body_html_path") or str(json_path).replace(".json", ".body.html")
    body_path = REPO_ROOT / body_path_relative
    if not body_path.exists():
        raise FileNotFoundError(f"Body HTML no encontrado: {body_path}")
    body_html = body_path.read_text(encoding="utf-8")
    return meta, body_html


def publish_blog(json_path: Path, client: ShopifyBlogClient, logger) -> dict:
    meta, body_html = load_blog(json_path)
    handle = meta["handle"]

    payload = {
        "title": meta["title"],
        "handle": handle,
        "body_html": body_html,
        "tags": meta.get("tags", ""),
        "summary_html": meta.get("summary_html", ""),
        "author": meta.get("author", "Equipo Yana"),
        "published": meta.get("published", True),
    }

    existing = client.find_by_handle(handle)
    if existing:
        article = client.update_article(existing["id"], payload)
        action = "actualizado"
    else:
        article = client.create_article(payload)
        action = "publicado"

    article_id = article["id"]

    # Metafields SEO (Shopify lee global.title_tag y global.description_tag)
    if meta.get("meta_title"):
        client.upsert_metafield(article_id, "global", "title_tag", meta["meta_title"])
    if meta.get("meta_description"):
        client.upsert_metafield(article_id, "global", "description_tag", meta["meta_description"])

    # Marcar como publicado en el JSON local
    meta["published_at"] = datetime.now(timezone.utc).isoformat()
    meta["shopify_article_id"] = article_id
    json_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    public_url = f"https://{client.base_url.split('/')[2]}/blogs/news/{handle}"
    logger.info(f"  ✓ {action}: {meta['title']}")
    logger.info(f"    URL admin: https://admin.shopify.com/store/{client.base_url.split('/')[2].split('.')[0]}/articles/{article_id}")

    return {"id": article_id, "handle": handle, "action": action}


def find_pending(blogs_dir: Path) -> list[Path]:
    pending = []
    for f in sorted(blogs_dir.glob("*.json")):
        try:
            meta = json.loads(f.read_text(encoding="utf-8"))
            if not meta.get("published_at"):
                pending.append(f)
        except json.JSONDecodeError:
            continue
    return pending


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", help="Path a JSON específico")
    parser.add_argument("--next", action="store_true", help="Publicar el siguiente pendiente")
    parser.add_argument("--all", action="store_true", help="Publicar todos los pendientes")
    parser.add_argument("--blog-id", type=int, default=DEFAULT_BLOG_ID, help="ID del blog destino en Shopify")
    args = parser.parse_args()

    load_env()
    logger = setup_logger("blog-publisher")
    shop = get_env("SHOPIFY_STORE")
    token = get_env("SHOPIFY_ACCESS_TOKEN")
    client = ShopifyBlogClient(shop=shop, access_token=token, blog_id=args.blog_id)

    if args.file:
        targets = [Path(args.file)]
    elif args.next:
        pending = find_pending(BLOGS_DIR)
        if not pending:
            logger.info("No hay blogs pendientes.")
            return
        targets = [pending[0]]
    elif args.all:
        targets = find_pending(BLOGS_DIR)
        if not targets:
            logger.info("No hay blogs pendientes.")
            return
    else:
        parser.print_help()
        return

    logger.info(f"Publicando {len(targets)} blog(s)...")
    for t in targets:
        try:
            publish_blog(t, client, logger)
        except Exception as e:
            logger.error(f"  ✗ Falló {t.name}: {e}")


if __name__ == "__main__":
    main()
