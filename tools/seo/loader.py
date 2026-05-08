"""
Carga la sección SEO del seo-system multi-tenant para un proyecto dado.

Adaptado de reporte-marfil/main.py:_load_seo_section. Lee:
- ../seo-system/output/{project}/reports/seo_dashboard.json (principal)
- ../seo-system/output/{project}/audits/latest_blog_audit.json (auditoría blogs)
- ../seo-system/output/{project}/auto_rewrites/*.json (cuenta rewrites hechos)
- ../seo-system/output/{project}/reports/published_log.json (blogs nuevos publicados)
- ../seo-system/output/{project}/reports/faq_injection_log.json (FAQ schema inyectados)
- ../seo-system/output/{project}/audits/2026*_blog_audit.json (evolución de score)
- ../seo-system/output/{project}/rankings/evolution.json (movimientos de keywords)

Calcula proyecciones de tráfico y revenue usando CTR de Google y un ticket
promedio configurable.

Returns None si no encuentra el seo_dashboard.json (no rompe el pipeline).
"""

import json
from pathlib import Path
from typing import Optional


# CTR promedio por posición en SERP de Google (datos públicos Advanced Web Ranking 2024)
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
    """
    project: clave en seo-system/config/stores.json
    ticket_eur: ticket promedio asumido para proyecciones (€)
    conv_rate: tasa de conversión click → venta asumida (default 2%)
    """
    repo_root = Path(__file__).resolve().parent.parent.parent
    seo_root = repo_root.parent / "seo-system" / "output" / project
    local_seo = repo_root / "seo" / "seo_dashboard.json"

    # Preferir el seo-system fresco; si no existe (ej. en GitHub Actions),
    # usar la copia local commiteada al repo.
    seo_path = seo_root / "reports" / "seo_dashboard.json"
    if not seo_path.exists():
        if local_seo.exists():
            seo_path = local_seo
            logger.info(f"SEO desde fallback local {local_seo}")
        else:
            logger.warning(f"SEO data no encontrada — el tab SEO mostrará vacío")
            return None

    try:
        with open(seo_path, encoding="utf-8") as f:
            seo = json.load(f)

        # ─── Auditoría de blogs ────────────────────────────────────────────
        avg_score = 0
        valid: list[dict] = []
        audit_path = seo_root / "audits" / "latest_blog_audit.json"
        if audit_path.exists():
            with open(audit_path, encoding="utf-8") as f:
                audit = json.load(f)
            valid = [a for a in audit.get("audits", []) if "seo_score" in a]
            avg_score = round(sum(a["seo_score"] for a in valid) / max(len(valid), 1), 1)
            seo["audit_summary"] = {
                "audited_at": audit.get("audited_at"),
                "total_articles": len(valid),
                "avg_score": avg_score,
                "score_distribution": {
                    "90+":     sum(1 for a in valid if a["seo_score"] >= 90),
                    "80-89":   sum(1 for a in valid if 80 <= a["seo_score"] < 90),
                    "70-79":   sum(1 for a in valid if 70 <= a["seo_score"] < 80),
                    "60-69":   sum(1 for a in valid if 60 <= a["seo_score"] < 70),
                    "50-59":   sum(1 for a in valid if 50 <= a["seo_score"] < 60),
                    "under_50": sum(1 for a in valid if a["seo_score"] < 50),
                },
                "worst_5": [
                    {"title": a["title"], "score": a["seo_score"], "handle": a.get("handle", "")}
                    for a in sorted(valid, key=lambda x: x["seo_score"])[:5]
                ],
            }

        # ─── Progress: trabajo realizado + evolución score ─────────────────
        rewrites_dir = seo_root / "auto_rewrites"
        n_rewrites = len(list(rewrites_dir.glob("*.json"))) if rewrites_dir.exists() else 0

        pub_log = seo_root / "reports" / "published_log.json"
        n_published = 0
        if pub_log.exists():
            with open(pub_log, encoding="utf-8") as f:
                n_published = len(json.load(f))

        faq_log = seo_root / "reports" / "faq_injection_log.json"
        n_faq = 0
        if faq_log.exists():
            with open(faq_log, encoding="utf-8") as f:
                n_faq = json.load(f).get("updated", 0)

        audits_dir = seo_root / "audits"
        evolution = []
        if audits_dir.exists():
            for ap in sorted(audits_dir.glob("2026*_blog_audit.json")):
                with open(ap, encoding="utf-8") as f:
                    a_data = json.load(f)
                a_valid = [x for x in a_data.get("audits", []) if "seo_score" in x]
                if len(a_valid) >= 20:
                    a_avg = round(sum(x["seo_score"] for x in a_valid) / len(a_valid), 1)
                    evolution.append({
                        "audit": ap.stem,
                        "audited_at": a_data.get("audited_at", ""),
                        "score": a_avg,
                        "articles": len(a_valid),
                    })

        starting_score = evolution[0]["score"] if evolution else avg_score
        improvement_pct = round(
            (avg_score - starting_score) / max(starting_score, 1) * 100, 1
        ) if starting_score else 0

        seo["progress"] = {
            "starting_avg_score": starting_score,
            "current_avg_score": avg_score,
            "improvement_pct": improvement_pct,
            "score_evolution": evolution,
            "achievements": [
                {"icon": "📊", "label": "Blogs auditados",                   "count": len(valid)},
                {"icon": "✍️",  "label": "Blogs reescritos con DataForSEO",  "count": n_rewrites},
                {"icon": "🆕", "label": "Blogs nuevos publicados",           "count": n_published},
                {"icon": "❓", "label": "Blogs con FAQ schema (PAA real)",   "count": n_faq},
                {"icon": "🎯", "label": "Blogs con score 70+",               "count": sum(1 for a in valid if a["seo_score"] >= 70)},
                {"icon": "⭐", "label": "Blogs con score 80+",               "count": sum(1 for a in valid if a["seo_score"] >= 80)},
            ],
        }

        # ─── Proyecciones tráfico + revenue ────────────────────────────────
        opps = seo.get("top_opportunities", [])
        rankings = seo.get("current_rankings", [])

        current_clicks = round(sum(
            r.get("volume", 0) * _ctr(r.get("position", 999)) for r in rankings
        ))
        opp_volume = sum(o.get("volume", 0) for o in opps)

        def scenario(name: str, target_pos: int, timeframe: str) -> dict:
            additional = round(opp_volume * _ctr(target_pos))
            total = current_clicks + additional
            sales = round(total * conv_rate)
            revenue = round(sales * ticket_eur)
            return {
                "name": name,
                "target_position": target_pos,
                "timeframe": timeframe,
                "additional_clicks_per_month": additional,
                "total_clicks_per_month": total,
                "estimated_sales_per_month": sales,
                "estimated_revenue_eur_per_month": revenue,
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

        # ─── Rankings evolution ────────────────────────────────────────────
        evo_path = seo_root / "rankings" / "evolution.json"
        if evo_path.exists():
            with open(evo_path, encoding="utf-8") as f:
                seo["rankings_evolution"] = json.load(f)
            logger.info(f"Rankings evolution cargada desde {evo_path.name}")

        logger.info(
            f"SEO cargado: score {avg_score}/100 sobre {len(valid)} blogs, "
            f"{len(opps)} oportunidades"
        )
        return seo

    except Exception as e:
        logger.warning(f"Error cargando SEO: {e}")
        return None
