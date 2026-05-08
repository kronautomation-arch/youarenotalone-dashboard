"""
Genera blogs automáticamente con Claude API a partir de los briefs del seo-system.

Pipeline diario:
1. Lee el siguiente brief no consumido en seo-system/output/youarenotalone/briefs/
2. Llama a Claude API con un prompt detallado (incluye brief + ejemplo de estilo)
3. Recibe HTML del cuerpo del blog
4. Guarda en blogs/YYYYMMDD-slug.{json,body.html}
5. Marca el brief como consumido (mueve a briefs/used/)

El primer blog manual (ropa-ecologica-mujer) se usa como referencia de estilo
para mantener la voz de la marca consistente.

Uso:
    python -m tools.blog.generator              # genera el siguiente
    python -m tools.blog.generator --dry-run    # genera pero no escribe ni mueve

Requiere ANTHROPIC_API_KEY en .env / GitHub Secrets.
"""

import argparse
import json
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from anthropic import Anthropic

from tools.core.env_loader import load_env, get_env
from tools.core.logger import setup_logger


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
BLOGS_DIR = REPO_ROOT / "blogs"
# Los briefs viven en el propio repo del dashboard (self-contained).
# Se generan localmente con seo-system y se copian aquí, o se consumen aquí.
BRIEFS_DIR = REPO_ROOT / "briefs"
USED_DIR = BRIEFS_DIR / "used"
REFERENCE_BLOG_PATH = BLOGS_DIR / "20260508-ropa-ecologica-mujer.body.html"

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """Eres redactora de contenido SEO de la marca Youarenotalone, ropa motivacional sobre salud mental, sostenibilidad y conexión humana en España.

VOZ DE MARCA — no negociable:
- Cálida, conversacional, honesta. Tuteo (no usted, no vosotros). Lenguaje directo.
- Anti-greenwashing: nombras certificaciones reales, llamas a las cosas por su nombre.
- Conectada con el universo de la marca: salud mental, comunidad, propósito, sostenibilidad.
- NUNCA exageras ni haces claims sin sustento.
- Los CTAs son sutiles, integrados al final, no invasivos.

ESTRUCTURA OBLIGATORIA del HTML que generas:
- Empieza con un párrafo de apertura emocional o con un dato impactante. SIN H1 (Shopify lo añade desde el title).
- 5-7 secciones con H2 (palabras clave secundarias en algunos H2)
- Listas <ul>/<ol>, tablas <table> cuando aporta. Énfasis con <strong> y <em>.
- Una sección "Preguntas frecuentes" con 5 H3 + respuestas.
- Después de las FAQs, un <script type="application/ld+json"> con el FAQPage schema con esas mismas 5 preguntas.
- Cierre con párrafo final + 1 sutil internal link a /collections/all.

REQUISITOS SEO:
- 1500-2000 palabras
- Keyword principal en el primer párrafo, en al menos 2 H2, y de manera natural en el cuerpo.
- Keywords secundarias integradas naturalmente.
- Internal link a /collections/all como CTA final.

OUTPUT: solo el HTML del body, sin markdown wrapping, sin explicaciones tuyas, sin <html>/<body>/<head>. Empieza directamente con el primer <p>."""


def slugify(text: str) -> str:
    """Convierte texto a slug URL-safe (sin tildes, lowercase, guiones)."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "-", text).strip("-")


def find_next_brief() -> Path | None:
    """Devuelve el path del siguiente brief no consumido (orden alfabético)."""
    if not BRIEFS_DIR.exists():
        return None
    candidates = sorted(BRIEFS_DIR.glob("2*.json"))  # ej: 20260507_*.json
    for p in candidates:
        if p.name == "next_batch.json":
            continue
        if (USED_DIR / p.name).exists():
            continue
        return p
    return None


def build_prompt(brief: dict, reference_html: str) -> str:
    keyword = brief["keyword"]
    serp = brief.get("serp_top_10", [])
    common_terms = brief.get("common_title_terms", [])

    serp_lines = "\n".join(
        f"  {r['rank']}. {r['title']} — {r['description'][:120]}"
        for r in serp[:10]
    )

    return f"""Necesito un blog optimizado para la keyword principal "{keyword}".

DATOS DE INVESTIGACIÓN SEO:
- Volumen mensual de búsqueda: {brief.get('volume_monthly', '?')}
- Dificultad SEO: {brief.get('difficulty', '?')}/100
- Términos comunes en titles del top 10: {', '.join(common_terms[:8])}

SERP TOP 10 ACTUAL (para que sepas con qué compites y qué cubrir):
{serp_lines}

KEYWORDS SECUNDARIAS a integrar naturalmente:
- {keyword.replace('mujer', 'femenina') if 'mujer' in keyword else keyword + ' calidad'}
- marcas {keyword.replace('ropa ', '').replace('moda ', '')} españa
- comprar {keyword}

EJEMPLO DE ESTILO (este es un blog ya publicado nuestro, replica su voz exacta):
---
{reference_html[:3500]}
[...continúa con el mismo tono hasta el FAQ schema final]
---

Ahora escribe el blog completo sobre "{keyword}" siguiendo TODAS las reglas del system prompt y replicando el estilo del ejemplo. Empieza directo con el primer <p>."""


def generate_blog(brief_path: Path, reference_html: str, client: Anthropic, logger) -> dict:
    brief = json.loads(brief_path.read_text(encoding="utf-8"))
    keyword = brief["keyword"]
    logger.info(f"Generando blog para: {keyword}")

    user_prompt = build_prompt(brief, reference_html)

    response = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        system=[
            {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
        ],
        messages=[{"role": "user", "content": user_prompt}],
    )

    body_html = response.content[0].text.strip()
    if body_html.startswith("```"):
        # Si Claude envolvió en code fence, removerlo
        body_html = re.sub(r"^```(?:html)?\n", "", body_html)
        body_html = re.sub(r"\n```\s*$", "", body_html)

    usage = response.usage
    logger.info(
        f"  tokens: in={usage.input_tokens} cache_read={getattr(usage, 'cache_read_input_tokens', 0)} "
        f"cache_create={getattr(usage, 'cache_creation_input_tokens', 0)} out={usage.output_tokens}"
    )

    # Construir metadata
    today = date.today().isoformat().replace("-", "")
    slug = slugify(keyword) + "-guia"
    title_base = keyword.capitalize()
    meta = {
        "handle": slug,
        "title": f"{title_base}: guía honesta y útil para España",
        "tags": f"{keyword}, moda sostenible, sostenibilidad, guía",
        "summary_html": f"<p>Todo lo que necesitas saber sobre {keyword} en España: materiales, certificaciones reales y cómo elegir bien.</p>",
        "meta_title": f"{title_base} {date.today().year} — Guía honesta | Youarenotalone",
        "meta_description": f"Guía completa sobre {keyword} en España. Certificaciones reales, marcas y cómo evitar greenwashing. Por Youarenotalone.",
        "body_html_path": f"blogs/{today}-{slug}.body.html",
        "primary_keyword": keyword,
        "secondary_keywords": brief.get("related_keywords", []) or [],
        "word_count_target": brief.get("recommended_word_count", 1500),
        "published_at": None,
        "generated_by": MODEL,
        "brief_source": brief_path.name,
    }

    return meta, body_html


def save_blog(meta: dict, body_html: str, today: str, logger) -> Path:
    BLOGS_DIR.mkdir(parents=True, exist_ok=True)
    slug = meta["handle"]
    json_path = BLOGS_DIR / f"{today}-{slug}.json"
    body_path = BLOGS_DIR / f"{today}-{slug}.body.html"

    json_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    body_path.write_text(body_html, encoding="utf-8")
    logger.info(f"  Guardado: {json_path.name} + {body_path.name}")
    return json_path


def mark_brief_used(brief_path: Path, logger) -> None:
    USED_DIR.mkdir(parents=True, exist_ok=True)
    target = USED_DIR / brief_path.name
    brief_path.rename(target)
    logger.info(f"  Brief movido a used/: {brief_path.name}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Genera pero no guarda ni mueve")
    args = parser.parse_args()

    load_env()
    logger = setup_logger("blog-generator")

    api_key = get_env("ANTHROPIC_API_KEY")
    client = Anthropic(api_key=api_key)

    brief_path = find_next_brief()
    if not brief_path:
        logger.warning("No hay briefs pendientes en seo-system/output/youarenotalone/briefs/")
        logger.warning("Corre 'python agent.py --store youarenotalone' en seo-system para refrescar.")
        sys.exit(1)

    if not REFERENCE_BLOG_PATH.exists():
        logger.error(f"Falta el blog de referencia: {REFERENCE_BLOG_PATH}")
        sys.exit(1)
    reference_html = REFERENCE_BLOG_PATH.read_text(encoding="utf-8")

    meta, body_html = generate_blog(brief_path, reference_html, client, logger)

    if args.dry_run:
        logger.info("DRY RUN — no se guarda ni se mueve")
        logger.info(f"Slug: {meta['handle']}")
        logger.info(f"Body length: {len(body_html)} chars")
        logger.info(f"Body preview:\n{body_html[:500]}\n...")
        return

    today = date.today().isoformat().replace("-", "")
    save_blog(meta, body_html, today, logger)
    mark_brief_used(brief_path, logger)

    logger.info(f"=== OK — blog generado para '{meta['primary_keyword']}' ===")


if __name__ == "__main__":
    main()
