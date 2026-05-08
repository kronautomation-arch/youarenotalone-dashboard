"""Carga la seccion SEO desde el payload pre-construido committeado al repo.

El payload `seo/payload.json` lo genera el script
`seo-system/tools/build_youarenotalone_payload.py` (corrida local) y se
commitea junto con el dashboard. En GitHub Actions no se intenta regenerar
ni leer del repo seo-system; el cron solo lee el archivo committeado.

Si el payload no existe, devuelve None (la seccion queda vacia, el
dashboard muestra empty-state, sin pisar datos previos).

Para recomputar proyecciones con un ticket distinto al hardcodeado en
el builder (default 50 EUR), pasar `ticket_eur` al loader.
"""

import json
from pathlib import Path
from typing import Optional


CTR = {
    1: 0.30, 2: 0.15, 3: 0.10, 4: 0.07, 5: 0.05,
    6: 0.04, 7: 0.03, 8: 0.025, 9: 0.02, 10: 0.018,
}


def _ctr(pos: int) -> float:
    return CTR.get(pos, 0.005) if pos <= 10 else 0.005


def load_seo_section(
    logger,
    project: str = "youarenotalone",
    ticket_eur: float = 50.0,
    conv_rate: float = 0.02,
) -> Optional[dict]:
    """Lee `seo/payload.json` y opcionalmente recomputa proyecciones con
    el ticket real del store (calculado desde Shopify).

    project se ignora — el payload es store-specific y el path esta fijo.
    Se mantiene en la firma por compatibilidad con main.py.
    """
    repo_root = Path(__file__).resolve().parent.parent.parent
    payload_path = repo_root / "seo" / "payload.json"

    if not payload_path.exists():
        logger.warning(f"SEO payload no encontrado en {payload_path} - tab SEO vacio")
        return None

    try:
        with open(payload_path, encoding="utf-8") as f:
            seo = json.load(f)
    except Exception as e:
        logger.warning(f"Error leyendo SEO payload: {e}")
        return None

    # Recomputar proyecciones si el ticket real difiere significativamente del default
    BUILDER_TICKET = 50.0
    if abs(ticket_eur - BUILDER_TICKET) > 1.0:
        opps = seo.get("top_opportunities", [])
        rankings = seo.get("current_rankings", [])
        current_clicks = round(sum(r.get("volume", 0) * _ctr(r.get("position", 999)) for r in rankings))
        opp_volume = sum(o.get("volume", 0) for o in opps)

        def scenario(name, target_pos, timeframe):
            additional = round(opp_volume * _ctr(target_pos))
            total = current_clicks + additional
            sales = round(total * conv_rate)
            return {
                "name": name,
                "target_position": target_pos,
                "timeframe": timeframe,
                "additional_clicks_per_month": additional,
                "total_clicks_per_month": total,
                "estimated_sales_per_month": sales,
                "estimated_revenue_eur_per_month": round(sales * ticket_eur),
            }

        seo["projections"] = {
            "current_estimated_clicks_per_month": current_clicks,
            "opportunity_volume_per_month": opp_volume,
            "assumptions": {
                "ticket_promedio_eur": ticket_eur,
                "conversion_rate": conv_rate,
                "ctr_table": "Google avg (pos 1=30%, pos 5=5%, pos 10=1.8%)",
            },
            "scenarios": [
                scenario("Conservador", 10, "6 meses"),
                scenario("Realista",     5, "6-12 meses"),
                scenario("Optimista",    3, "12-18 meses"),
            ],
        }

    summary = seo.get("audit_summary", {})
    logger.info(
        f"SEO cargado del payload: score {summary.get('avg_score', 0)}/100 "
        f"sobre {summary.get('total_articles', 0)} blogs, "
        f"{len(seo.get('top_opportunities', []))} oportunidades"
    )
    return seo
