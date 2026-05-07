"""
Dashboard Youarenotalone — pipeline orquestador.

Lee Shopify (España, EUR, paid_only=False) + Meta Ads + SEO multi-tenant,
agrega por día, calcula KPIs, genera 20 logros via reglas Python, y vuelca
a dashboard.json + dashboard/data.json.

Diseño WAT:
- TOOLS: scripts deterministas en tools/
- AGENT: este script orquesta sin LLM
- WORKFLOWS: documentación en CLAUDE.md y plan
"""

import json
import shutil
import traceback
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore

from tools.core.env_loader import load_env, get_env
from tools.core.logger import setup_logger
from tools.shopify.shopify_client import ShopifyClient, ShopifyAPIError
from tools.meta.meta_client import MetaAdsClient, MetaAPIError
from tools.seo.loader import load_seo_section
from tools.achievements.rules import generar_logros
from tools.forex.forex_client import get_daily_rates


REPO_ROOT = Path(__file__).resolve().parent
DASHBOARD_JSON = REPO_ROOT / "dashboard.json"
DASHBOARD_DATA_JSON = REPO_ROOT / "dashboard" / "data.json"
TZ_NAME = "Europe/Madrid"
TZ_OFFSET = "+01:00"  # CET; en verano (CEST) será +02:00 — Shopify acepta ambos
SEO_PROJECT = "youarenotalone"
TICKET_DEFAULT_EUR = 50.0  # ticket por defecto para proyecciones SEO si no hay ventas


# ──────────────────────────────────────────────────────────────────────────
# Helpers de período
# ──────────────────────────────────────────────────────────────────────────

def _madrid_offset(today: date) -> str:
    """Devuelve '+02:00' en horario de verano (CEST), '+01:00' en invierno (CET)."""
    tz = ZoneInfo(TZ_NAME)
    now = datetime.combine(today, datetime.min.time(), tzinfo=tz)
    offset = now.utcoffset() or timedelta(hours=1)
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    hh = abs(total_minutes) // 60
    mm = abs(total_minutes) % 60
    return f"{sign}{hh:02d}:{mm:02d}"


def _slice_dates(today: date, period: str) -> tuple[date, date]:
    """Devuelve (inicio, fin) inclusive según el período."""
    if period == "hoy":
        return today, today
    if period == "semana":
        # Lunes de esta semana hasta hoy
        inicio = today - timedelta(days=today.weekday())
        return inicio, today
    if period == "mes":
        return date(today.year, today.month, 1), today
    if period == "ytd":
        return date(today.year, 1, 1), today
    raise ValueError(f"Período desconocido: {period}")


def _label(period: str) -> str:
    return {
        "hoy": "hoy",
        "semana": "esta semana",
        "mes": "este mes",
        "ytd": "este año",
    }[period]


# ──────────────────────────────────────────────────────────────────────────
# Construir daily desde Shopify + Meta
# ──────────────────────────────────────────────────────────────────────────

def _build_daily(shopify_data: dict | None, meta_data: dict | None) -> dict:
    """
    Combina historial_diario de Shopify y Meta en un dict {fecha: {...}}.
    """
    daily: dict[str, dict] = defaultdict(lambda: {
        "ventas_brutas": 0.0,
        "ventas_netas": 0.0,
        "descuentos": 0.0,
        "unidades": 0,
        "ordenes": 0,
        "meta_gasto": 0.0,
        "meta_purchases": 0,
        "meta_clicks": 0,
        "meta_impressions": 0,
        "meta_reach": 0,
    })

    if shopify_data:
        for d in shopify_data.get("historial_diario", []):
            fecha = d["fecha"]
            daily[fecha]["ventas_brutas"] += d.get("ventas_brutas", 0)
            daily[fecha]["ventas_netas"] += d.get("ventas_netas", 0)
            daily[fecha]["descuentos"] += d.get("descuentos", 0)
            daily[fecha]["unidades"] += d.get("unidades", 0)
            daily[fecha]["ordenes"] += d.get("ordenes", 0)

    if meta_data:
        for d in meta_data.get("historial_diario", []):
            fecha = d["fecha"]
            daily[fecha]["meta_gasto"] += d.get("gasto", 0)
            daily[fecha]["meta_purchases"] += d.get("purchases", 0)
            daily[fecha]["meta_clicks"] += d.get("clicks", 0)
            daily[fecha]["meta_impressions"] += d.get("impressions", 0)
            daily[fecha]["meta_reach"] += d.get("reach", 0)

    # Redondear ventas a 2 decimales
    for fecha in daily:
        for k in ("ventas_brutas", "ventas_netas", "descuentos", "meta_gasto"):
            daily[fecha][k] = round(daily[fecha][k], 2)

    return dict(sorted(daily.items()))


def _agg(daily: dict, inicio: date, fin: date) -> dict:
    """Agrega los días del rango [inicio, fin] inclusive."""
    inicio_s, fin_s = inicio.isoformat(), fin.isoformat()
    out = {
        "ventas_brutas": 0.0, "ventas_netas": 0.0, "descuentos": 0.0,
        "unidades": 0, "ordenes": 0,
        "meta_gasto": 0.0, "meta_purchases": 0, "meta_clicks": 0,
        "meta_impressions": 0, "meta_reach": 0,
    }
    for fecha, d in daily.items():
        if inicio_s <= fecha <= fin_s:
            for k in out:
                out[k] += d.get(k, 0)
    for k in ("ventas_brutas", "ventas_netas", "descuentos", "meta_gasto"):
        out[k] = round(out[k], 2)
    return out


def _slice_to_logros_input(
    agg: dict,
    shopify_data: dict | None,
    meta_data: dict | None,
) -> dict:
    """
    Construye la estructura que necesita generar_logros() a partir de los
    agregados del período + datos globales (top_productos, ctr global, etc.).
    """
    ventas_netas = agg["ventas_netas"]
    ventas_brutas = agg["ventas_brutas"]
    ordenes = agg["ordenes"]
    unidades = agg["unidades"]
    descuentos = agg["descuentos"]
    gasto_meta = agg["meta_gasto"]
    purchases_meta = agg["meta_purchases"]
    impressions = agg["meta_impressions"]
    clicks = agg["meta_clicks"]
    reach = agg["meta_reach"]  # suma diaria — no es reach real único, es proxy

    ticket = (ventas_netas / ordenes) if ordenes > 0 else 0
    tasa_descuento = (descuentos / ventas_brutas) if ventas_brutas > 0 else 0
    roas = (ventas_netas / gasto_meta) if gasto_meta > 0 else 0
    cpa = (gasto_meta / ordenes) if ordenes > 0 else 0
    ctr = (clicks / impressions * 100) if impressions > 0 else 0
    frequency = (impressions / reach) if reach > 0 else 0

    # Top productos vienen de los datos globales de Shopify (no por día)
    top_productos = (shopify_data or {}).get("top_productos", [])

    return {
        "meta": {
            "reach": reach,
            "impressions": impressions,
            "clicks": clicks,
            "ctr": ctr,
            "frequency": frequency,
            "gasto": gasto_meta,
            "purchases": purchases_meta,
        },
        "shopify": {
            "ventas_netas": ventas_netas,
            "ventas_brutas": ventas_brutas,
            "descuentos": descuentos,
            "unidades": unidades,
            "ordenes": ordenes,
            "ticket_promedio": ticket,
            "tasa_descuento": tasa_descuento,
            "top_productos": top_productos,
        },
        "roas": roas,
        "cpa": cpa,
    }


# ──────────────────────────────────────────────────────────────────────────
# Pipeline principal
# ──────────────────────────────────────────────────────────────────────────

def main():
    load_env()
    logger = setup_logger()
    logger.info("=== YOUARENOTALONE DASHBOARD — Inicio de actualización ===")

    today = date.today()
    inicio_ano = date(today.year, 1, 1)
    tz = ZoneInfo(TZ_NAME)
    offset = _madrid_offset(today)
    updated_at = datetime.now(tz).isoformat(timespec="seconds")

    errors = {"shopify": None, "meta": None, "seo": None}

    # ─── SHOPIFY ──────────────────────────────────────────────────────────
    shopify_data = None
    try:
        shop = get_env("SHOPIFY_STORE")
        token = get_env("SHOPIFY_ACCESS_TOKEN")
        shopify_client = ShopifyClient(
            shop=shop,
            access_token=token,
            tz_offset=offset,
            paid_only=False,
        )
        logger.info(f"Shopify: descargando órdenes desde {inicio_ano} hasta {today}...")
        shopify_data = shopify_client.get_resumen_ventas(inicio_ano, today)
        logger.info(
            f"Shopify OK: {shopify_data['ordenes']} órdenes, "
            f"{shopify_data['unidades']} unidades, "
            f"{shopify_data['ventas_netas']} € netos YTD"
        )
    except (ShopifyAPIError, EnvironmentError) as e:
        errors["shopify"] = str(e)
        logger.error(f"Shopify falló: {e}")
    except Exception as e:
        errors["shopify"] = f"{type(e).__name__}: {e}"
        logger.error(f"Shopify error inesperado: {traceback.format_exc()}")

    # ─── META ADS ─────────────────────────────────────────────────────────
    meta_data = None
    try:
        token = get_env("META_ACCESS_TOKEN")
        ids_raw = get_env("META_ACCOUNT_IDS")
        account_ids = [a.strip() for a in ids_raw.split(",") if a.strip()]
        meta_client = MetaAdsClient(access_token=token, account_ids=account_ids)
        logger.info(f"Meta: descargando insights de {len(account_ids)} cuenta(s)...")
        meta_data = meta_client.get_all_accounts_data(inicio_ano, today)
        logger.info(
            f"Meta OK (nativo): gasto total {meta_data['gasto_total']:.2f}, "
            f"{meta_data['purchases_total']} purchases YTD"
        )

        # ─── Conversión de divisas si la cuenta no está en EUR ─────────
        for c in meta_data["cuentas"]:
            c["currency"] = meta_client.get_account_currency(c["account_id"])

        currencies = [c["currency"] for c in meta_data["cuentas"]]
        native_currency = currencies[0] if currencies else "EUR"
        all_same = all(c == native_currency for c in currencies)

        if native_currency != "EUR":
            if not all_same:
                logger.warning(
                    f"Múltiples monedas en cuentas Meta {set(currencies)} — "
                    f"usando {native_currency} para conversión global"
                )
            rates = get_daily_rates(
                base=native_currency, target="EUR",
                start=inicio_ano, end=today, logger=logger,
            )
            avg_rate = sum(rates.values()) / len(rates) if rates else 1.0

            # Convertir historial diario con tasa de cada día
            for d in meta_data["historial_diario"]:
                rate = rates.get(d["fecha"], avg_rate)
                d["gasto"] = round(d["gasto"] * rate, 2)

            # Convertir agregados por cuenta (usamos avg_rate del período)
            for c in meta_data["cuentas"]:
                c["gasto"]  = round(c["gasto"]  * avg_rate, 2)
                c["cpa"]    = round(c["cpa"]    * avg_rate, 2)
                c["cpm"]    = round(c.get("cpm", 0) * avg_rate, 2)

            # Top-level
            meta_data["gasto_total"] = round(meta_data["gasto_total"] * avg_rate, 2)
            meta_data["cpa"]         = round(meta_data["cpa"]         * avg_rate, 2)
            agg = meta_data.get("agregado", {})
            agg["cpm"] = round(agg.get("cpm", 0) * avg_rate, 2)
            agg["cpc"] = round(agg.get("cpc", 0) * avg_rate, 4)

            meta_data["currency_conversion"] = {
                "from": native_currency,
                "to": "EUR",
                "method": "daily_historical_rates",
                "avg_rate": round(avg_rate, 8),
                "source": "fawazahmed0/exchange-api",
            }

            logger.info(
                f"Meta convertido {native_currency}→EUR: tasa promedio {avg_rate:.8f}, "
                f"gasto total ahora {meta_data['gasto_total']:.2f} €"
            )
    except (MetaAPIError, EnvironmentError) as e:
        errors["meta"] = str(e)
        logger.error(f"Meta falló: {e}")
    except Exception as e:
        errors["meta"] = f"{type(e).__name__}: {e}"
        logger.error(f"Meta error inesperado: {traceback.format_exc()}")

    # ─── SEO ──────────────────────────────────────────────────────────────
    # Ticket usado para proyecciones: si tenemos ventas, usar ticket real.
    # Si no, fallback al default.
    ticket_for_seo = TICKET_DEFAULT_EUR
    if shopify_data and shopify_data["ordenes"] > 0:
        ticket_for_seo = shopify_data["ventas_netas"] / shopify_data["ordenes"]

    seo_section = None
    try:
        seo_section = load_seo_section(
            logger,
            project=SEO_PROJECT,
            ticket_eur=ticket_for_seo,
            conv_rate=0.02,
        )
    except Exception as e:
        errors["seo"] = f"{type(e).__name__}: {e}"
        logger.error(f"SEO error: {traceback.format_exc()}")

    # ─── DAILY ────────────────────────────────────────────────────────────
    daily = _build_daily(shopify_data, meta_data)
    logger.info(f"Daily: {len(daily)} días con datos")

    # ─── KPIs YTD agregados ───────────────────────────────────────────────
    ytd_inicio, ytd_fin = _slice_dates(today, "ytd")
    agg_ytd = _agg(daily, ytd_inicio, ytd_fin)
    ticket_ytd = (agg_ytd["ventas_netas"] / agg_ytd["ordenes"]) if agg_ytd["ordenes"] > 0 else 0
    roas_ytd = (agg_ytd["ventas_netas"] / agg_ytd["meta_gasto"]) if agg_ytd["meta_gasto"] > 0 else 0
    tasa_desc_ytd = (agg_ytd["descuentos"] / agg_ytd["ventas_brutas"]) if agg_ytd["ventas_brutas"] > 0 else 0
    upo_ytd = (agg_ytd["unidades"] / agg_ytd["ordenes"]) if agg_ytd["ordenes"] > 0 else 0

    # ─── LOGROS ───────────────────────────────────────────────────────────
    logros = {}
    for period in ["hoy", "semana", "mes", "ytd"]:
        inicio, fin = _slice_dates(today, period)
        agg = _agg(daily, inicio, fin)
        slice_input = _slice_to_logros_input(agg, shopify_data, meta_data)
        logros[period] = generar_logros(slice_input, _label(period), seo=seo_section)

    # ─── DASHBOARD JSON ───────────────────────────────────────────────────
    dashboard = {
        "updated_at": updated_at,
        "currency": "EUR",
        "locale": "es-ES",
        "timezone": TZ_NAME,
        "errors": errors,

        "config": {
            "marca": "Youarenotalone",
            "pais": "España",
            "ticket_promedio": round(ticket_ytd, 2),
            "fuente_primaria": "shopify",
        },

        "shopify": {
            "ventas_brutas_ytd":  agg_ytd["ventas_brutas"]  if shopify_data else 0,
            "ventas_netas_ytd":   agg_ytd["ventas_netas"]   if shopify_data else 0,
            "descuentos_ytd":     agg_ytd["descuentos"]     if shopify_data else 0,
            "unidades_ytd":       agg_ytd["unidades"]       if shopify_data else 0,
            "ordenes_ytd":        agg_ytd["ordenes"]        if shopify_data else 0,
            "canceladas":         (shopify_data or {}).get("canceladas",   {"ordenes": 0, "monto": 0}),
            "reembolsadas":       (shopify_data or {}).get("reembolsadas", {"ordenes": 0, "monto": 0}),
            "no_pagadas":         (shopify_data or {}).get("no_pagadas",   {"ordenes": 0, "monto": 0}),
            "top_productos":      (shopify_data or {}).get("top_productos", []),
            "top_skus":           (shopify_data or {}).get("top_skus", []),
            "canales":            (shopify_data or {}).get("canales", []),
            "codigos_descuento":  (shopify_data or {}).get("codigos_descuento", []),
        },

        "meta": {
            "gasto_total_ytd":    (meta_data or {}).get("gasto_total", 0),
            "purchases_total_ytd": (meta_data or {}).get("purchases_total", 0),
            "cpa":                (meta_data or {}).get("cpa", 0),
            "cuentas":            (meta_data or {}).get("cuentas", []),
            "agregado_ytd":       (meta_data or {}).get("agregado", {
                "impressions": 0, "reach": 0, "clicks": 0,
                "ctr": 0, "cpm": 0, "frequency": 0, "cpc": 0,
            }),
            "currency_conversion": (meta_data or {}).get("currency_conversion"),
        },

        "kpis_negocio": {
            "roas_ytd":          round(roas_ytd, 2),
            "ticket_promedio":   round(ticket_ytd, 2),
            "tasa_descuento":    round(tasa_desc_ytd, 4),
            "unidades_por_orden": round(upo_ytd, 2),
        },

        "daily": daily,

        "seo": seo_section,

        "logros": logros,
    }

    # ─── ESCRIBIR JSON ────────────────────────────────────────────────────
    DASHBOARD_JSON.write_text(
        json.dumps(dashboard, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    DASHBOARD_DATA_JSON.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(DASHBOARD_JSON, DASHBOARD_DATA_JSON)
    logger.info(f"Dashboard escrito en {DASHBOARD_JSON} y copiado a {DASHBOARD_DATA_JSON}")

    # Resumen final
    n_logros = sum(len(v["all"]) for v in logros.values())
    logger.info(
        f"=== FIN — {n_logros} logros generados, "
        f"errores: {sum(1 for v in errors.values() if v)} ==="
    )


if __name__ == "__main__":
    main()
