"""
Genera briefs SEO consultando DataForSEO directamente. Autocontenido.

Reemplaza la dependencia del seo-system externo. Cuando el workflow
blog-daily detecta que no hay briefs pendientes en briefs/, llama a
este script para refrescar.

Pipeline:
1. Lee seo/seed_keywords.json
2. Para cada seed, consulta DataForSEO Labs keyword_ideas (España, ES)
3. Filtra por volumen mínimo, dificultad máxima, exclusiones
4. Excluye keywords ya cubiertas (briefs/ + briefs/used/)
5. Toma top N por opportunity (volumen / max(dificultad, 1))
6. Para cada keyword, descarga SERP top 10 organic
7. Escribe brief en briefs/YYYYMMDD_keyword.json

Costo aprox: ~$0.05 USD por refresh (10 seed_keywords + 8 SERPs).

Uso:
    python -m tools.seo.brief_generator              # refrescar
    python -m tools.seo.brief_generator --dry-run    # solo listar oportunidades

Requiere DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD en .env / Secrets.
"""

import argparse
import json
import re
import sys
import unicodedata
from base64 import b64encode
from datetime import date
from pathlib import Path
from typing import Optional

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tools.core.env_loader import load_env, get_env
from tools.core.logger import setup_logger


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BRIEFS_DIR = REPO_ROOT / "briefs"
USED_DIR = BRIEFS_DIR / "used"
SEED_PATH = REPO_ROOT / "seo" / "seed_keywords.json"

DFS_BASE = "https://api.dataforseo.com/v3"
TIMEOUT = 60


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


class DataForSEOClient:
    def __init__(self, login: str, password: str):
        creds = b64encode(f"{login}:{password}".encode()).decode()
        self.headers = {
            "Authorization": f"Basic {creds}",
            "Content-Type": "application/json",
        }

    def keyword_suggestions(self, seed: str, location: int, language: str, limit: int = 100) -> list[dict]:
        """Devuelve keywords que contienen literalmente la frase seed (long-tails)."""
        url = f"{DFS_BASE}/dataforseo_labs/google/keyword_suggestions/live"
        payload = [{
            "keyword": seed,
            "location_code": location,
            "language_code": language,
            "limit": limit,
            "filters": [["keyword_info.search_volume", ">=", 20]],
            "order_by": ["keyword_info.search_volume,desc"],
        }]
        r = requests.post(url, json=payload, headers=self.headers, timeout=TIMEOUT)
        r.raise_for_status()
        result = r.json().get("tasks", [{}])[0].get("result")
        if not result:
            return []
        items = result[0].get("items") or []
        out = []
        for it in items:
            ki = it.get("keyword_info") or {}
            kp = it.get("keyword_properties") or {}
            out.append({
                "keyword": it.get("keyword", ""),
                "volume": ki.get("search_volume") or 0,
                "difficulty": kp.get("keyword_difficulty") or 0,
                "cpc": ki.get("cpc") or 0,
                "competition": ki.get("competition") or 0,
            })
        return out

    def serp_organic(self, keyword: str, location: int, language: str) -> list[dict]:
        url = f"{DFS_BASE}/serp/google/organic/live/advanced"
        payload = [{
            "keyword": keyword,
            "location_code": location,
            "language_code": language,
            "depth": 10,
            "device": "desktop",
        }]
        r = requests.post(url, json=payload, headers=self.headers, timeout=TIMEOUT)
        r.raise_for_status()
        result = r.json().get("tasks", [{}])[0].get("result")
        if not result:
            return []
        items = result[0].get("items") or []
        organic = []
        for it in items:
            if it.get("type") != "organic":
                continue
            organic.append({
                "rank": it.get("rank_absolute"),
                "title": it.get("title", ""),
                "url": it.get("url", ""),
                "description": it.get("description", "") or "",
            })
            if len(organic) >= 10:
                break
        return organic


def existing_keywords(briefs_dir: Path, used_dir: Path) -> set[str]:
    """Devuelve set de slugs ya cubiertos (pendientes + usados)."""
    out = set()
    for d in (briefs_dir, used_dir):
        if not d.exists():
            continue
        for p in d.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                kw = data.get("keyword")
                if kw:
                    out.add(slugify(kw))
            except (json.JSONDecodeError, OSError):
                # Fallback al filename
                stem = p.stem
                # 20260507_ropa_ecologica_mujer → ropa_ecologica_mujer
                parts = stem.split("_", 1)
                if len(parts) == 2:
                    out.add(parts[1])
    return out


def write_brief(brief: dict, briefs_dir: Path, today: str) -> Path:
    slug = slugify(brief["keyword"])
    out_path = briefs_dir / f"{today}_{slug}.json"
    out_path.write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Lista oportunidades sin descargar SERP ni escribir")
    args = parser.parse_args()

    load_env()
    logger = setup_logger("brief-generator")

    config = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    seeds = config["seed_keywords"]
    location = config.get("location_code", 2724)
    language = config.get("language_code", "es")
    top_n = config.get("top_briefs_per_refresh", 8)
    min_vol = config.get("min_volume", 30)
    max_diff = config.get("max_difficulty", 50)
    excludes = [e.lower() for e in config.get("exclude_keywords_containing", [])]

    client = DataForSEOClient(
        login=get_env("DATAFORSEO_LOGIN"),
        password=get_env("DATAFORSEO_PASSWORD"),
    )

    logger.info(
        f"Refresh briefs: {len(seeds)} seeds, location={location}, "
        f"vol>={min_vol}, diff<={max_diff}"
    )

    BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    USED_DIR.mkdir(parents=True, exist_ok=True)

    # Recolectar oportunidades
    all_kw: dict[str, dict] = {}
    for seed in seeds:
        try:
            kws = client.keyword_suggestions(seed, location, language)
            logger.info(f"  '{seed}': {len(kws)} resultados")
            for k in kws:
                kw_lower = k["keyword"].lower()
                if k["volume"] < min_vol or k["difficulty"] > max_diff:
                    continue
                if any(ex in kw_lower for ex in excludes):
                    continue
                k["opportunity"] = round(k["volume"] / max(k["difficulty"], 1), 1)
                # Si ya está, quedarse con la mejor opportunity
                existing = all_kw.get(k["keyword"])
                if existing is None or k["opportunity"] > existing["opportunity"]:
                    all_kw[k["keyword"]] = k
        except Exception as e:
            logger.warning(f"  Error con seed '{seed}': {e}")

    # Excluir ya cubiertas
    covered = existing_keywords(BRIEFS_DIR, USED_DIR)
    new_opps = [k for kw, k in all_kw.items() if slugify(kw) not in covered]
    new_opps.sort(key=lambda x: x["opportunity"], reverse=True)
    new_opps = new_opps[:top_n]

    logger.info(
        f"  Total filtradas: {len(all_kw)}, ya cubiertas: {len(all_kw) - len(new_opps)}, "
        f"nuevas top {top_n}: {len(new_opps)}"
    )

    if not new_opps:
        logger.warning("Sin nuevas oportunidades. Revisa seed_keywords o relaja filtros.")
        return

    if args.dry_run:
        logger.info("DRY RUN — no se escriben briefs ni se descarga SERP")
        for k in new_opps:
            logger.info(
                f"  - {k['keyword']:50s} vol={k['volume']:5d} diff={k['difficulty']:2d} opp={k['opportunity']}"
            )
        return

    # Escribir briefs con SERP
    today = date.today().isoformat().replace("-", "")
    written = 0
    for k in new_opps:
        kw = k["keyword"]
        try:
            serp = client.serp_organic(kw, location, language)
        except Exception as e:
            logger.warning(f"  SERP failed para '{kw}': {e}")
            serp = []

        # Términos comunes de los titles del top 10
        title_words: dict[str, int] = {}
        for r in serp:
            for w in re.findall(r"\b\w{3,}\b", r["title"].lower()):
                title_words[w] = title_words.get(w, 0) + 1
        common = [w for w, c in sorted(title_words.items(), key=lambda x: -x[1])[:10]]

        brief = {
            "keyword": kw,
            "volume_monthly": k["volume"],
            "difficulty": k["difficulty"],
            "opportunity": k["opportunity"],
            "related_keywords": [],
            "serp_top_10": serp,
            "common_title_terms": common,
            "suggested_outline": [],
            "recommended_word_count": 1500,
            "meta_title_template": f"{kw.capitalize()} | Youarenotalone",
            "meta_desc_template": f"Guía completa sobre {kw} en España. Por Youarenotalone.",
            "internal_link_suggestions": [
                "Link a colección principal",
                "Link a 2-3 artículos relacionados ya publicados",
            ],
            "tone_and_voice": {
                "audience": "Compradores potenciales en España",
                "tone": "Informativo, autoritario pero accesible. Tuteo.",
                "avoid": "Lenguaje genérico, claims sin sustento, exageraciones",
            },
        }
        path = write_brief(brief, BRIEFS_DIR, today)
        written += 1
        logger.info(
            f"  + {kw:50s} vol={k['volume']:5d} diff={k['difficulty']:2d} → {path.name}"
        )

    logger.info(f"OK — {written} briefs escritos en {BRIEFS_DIR.relative_to(REPO_ROOT)}/")


if __name__ == "__main__":
    main()
