"""
Client para la API de Meta Marketing (Facebook Ads).
Obtiene métricas de gasto publicitario, alcance, impresiones, etc.

Base URL: https://graph.facebook.com/v21.0/
Auth: Access token de larga duración

NOTA: Este cliente es copia exacta del usado en reporte-marfil. Devuelve
campos genéricos (spend, impressions, clicks, purchases). El reach y la
frequency se obtienen vía un campo adicional con get_account_insights_full
añadido al final.
"""

import requests
from datetime import date
from typing import Optional


class MetaAPIError(Exception):
    """Error devuelto por la API de Meta. Incluye detalles útiles (no el token)."""
    pass


class MetaAdsClient:
    BASE_URL = "https://graph.facebook.com/v21.0"

    def __init__(self, access_token: str, account_ids: list[str]):
        """
        access_token: Token de acceso de Meta (larga duración).
        account_ids: Lista de IDs de cuentas publicitarias (ej: ["act_123", "act_456"]).
        """
        self.access_token = access_token
        self.account_ids = account_ids

    def _get(self, endpoint: str, params: Optional[dict] = None) -> dict:
        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"
        if params is None:
            params = {}
        params["access_token"] = self.access_token
        response = requests.get(url, params=params, timeout=30)
        if not response.ok:
            try:
                err = response.json().get("error", {})
                meta_msg = err.get("message", response.text)
                meta_type = err.get("type", "?")
                meta_code = err.get("code", "?")
                fbtrace = err.get("fbtrace_id", "?")
                raise MetaAPIError(
                    f"Meta API {response.status_code} en {endpoint} — "
                    f"{meta_type} (code {meta_code}): {meta_msg} [fbtrace_id={fbtrace}]"
                )
            except ValueError:
                raise MetaAPIError(
                    f"Meta API {response.status_code} en {endpoint} — respuesta no-JSON: {response.text[:500]}"
                )
        return response.json()

    def get_account_currency(self, account_id: str) -> str:
        """Devuelve el código ISO de la moneda nativa de una cuenta publicitaria (ej: 'COP', 'EUR', 'USD')."""
        try:
            data = self._get(f"{account_id}", {"fields": "currency"})
            return (data.get("currency") or "EUR").upper()
        except MetaAPIError:
            return "EUR"  # fallback razonable

    def get_account_insights(self, account_id: str, fecha_inicio: date, fecha_fin: date) -> dict:
        """
        Insights agregados de una cuenta. Incluye reach y frequency
        (necesarios para las reglas de logros).
        """
        params = {
            "fields": "spend,impressions,clicks,actions,cost_per_action_type,cpc,reach,frequency,ctr,cpm",
            "time_range": f'{{"since":"{fecha_inicio.isoformat()}","until":"{fecha_fin.isoformat()}"}}',
            "level": "account",
        }

        data = self._get(f"{account_id}/insights", params)
        results = data.get("data", [])

        if not results:
            return {
                "spend": 0.0, "impressions": 0, "clicks": 0, "purchases": 0,
                "cpa": 0.0, "cpc": 0.0, "reach": 0, "frequency": 0.0,
                "ctr": 0.0, "cpm": 0.0,
            }

        row = results[0]

        purchases = 0
        actions = row.get("actions", [])
        for action in actions:
            if action.get("action_type") in ("purchase", "offsite_conversion.fb_pixel_purchase"):
                purchases += int(action.get("value", 0))

        cpa = 0.0
        cost_per_actions = row.get("cost_per_action_type", [])
        for cpa_item in cost_per_actions:
            if cpa_item.get("action_type") in ("purchase", "offsite_conversion.fb_pixel_purchase"):
                cpa = float(cpa_item.get("value", 0))

        return {
            "spend": float(row.get("spend", 0)),
            "impressions": int(row.get("impressions", 0)),
            "clicks": int(row.get("clicks", 0)),
            "purchases": purchases,
            "cpa": cpa,
            "cpc": float(row.get("cpc", 0)),
            "reach": int(row.get("reach", 0)),
            "frequency": float(row.get("frequency", 0)),
            "ctr": float(row.get("ctr", 0)),
            "cpm": float(row.get("cpm", 0)),
        }

    def get_account_daily_insights(self, account_id: str, fecha_inicio: date, fecha_fin: date) -> list[dict]:
        """Insights diarios de una cuenta (para histograma)."""
        params = {
            "fields": "spend,impressions,clicks,actions,reach",
            "time_range": f'{{"since":"{fecha_inicio.isoformat()}","until":"{fecha_fin.isoformat()}"}}',
            "time_increment": 1,
            "level": "account",
            "limit": 400,
        }

        data = self._get(f"{account_id}/insights", params)
        results = data.get("data", [])

        daily = []
        for row in results:
            purchases = 0
            for action in row.get("actions", []):
                if action.get("action_type") in ("purchase", "offsite_conversion.fb_pixel_purchase"):
                    purchases += int(action.get("value", 0))

            daily.append({
                "fecha": row.get("date_start", ""),
                "spend": float(row.get("spend", 0)),
                "impressions": int(row.get("impressions", 0)),
                "clicks": int(row.get("clicks", 0)),
                "purchases": purchases,
                "reach": int(row.get("reach", 0)),
            })

        return daily

    def get_all_accounts_data(self, fecha_inicio: date, fecha_fin: date) -> dict:
        """
        Datos de todas las cuentas configuradas.

        Retorna:
        {
            gasto_total, purchases_total, cpa,
            cuentas: [{nombre, account_id, gasto, impressions, clicks, purchases, cpa, reach, frequency, ctr, cpm}],
            historial_diario: [{fecha, gasto, impressions, clicks, purchases, reach}],
            agregado: {impressions, reach, clicks, ctr, cpm, frequency}
        }
        """
        cuentas = []
        gasto_total = 0
        purchases_total = 0
        impressions_total = 0
        clicks_total = 0
        reach_total = 0
        all_daily = {}

        for i, account_id in enumerate(self.account_ids):
            account_id = account_id.strip()
            if not account_id:
                continue

            insights = self.get_account_insights(account_id, fecha_inicio, fecha_fin)
            nombre = f"Cuenta {str(i + 1).zfill(2)}"

            cuentas.append({
                "nombre": nombre,
                "account_id": account_id,
                "gasto": insights["spend"],
                "impressions": insights["impressions"],
                "clicks": insights["clicks"],
                "purchases": insights["purchases"],
                "cpa": insights["cpa"],
                "reach": insights["reach"],
                "frequency": insights["frequency"],
                "ctr": insights["ctr"],
                "cpm": insights["cpm"],
            })

            gasto_total += insights["spend"]
            purchases_total += insights["purchases"]
            impressions_total += insights["impressions"]
            clicks_total += insights["clicks"]
            reach_total += insights["reach"]

            daily = self.get_account_daily_insights(account_id, fecha_inicio, fecha_fin)
            for day in daily:
                fecha = day["fecha"]
                if fecha not in all_daily:
                    all_daily[fecha] = {
                        "gasto": 0.0, "impressions": 0, "clicks": 0,
                        "purchases": 0, "reach": 0,
                    }
                all_daily[fecha]["gasto"] += day["spend"]
                all_daily[fecha]["impressions"] += day["impressions"]
                all_daily[fecha]["clicks"] += day["clicks"]
                all_daily[fecha]["purchases"] += day["purchases"]
                all_daily[fecha]["reach"] += day["reach"]

        cpa_total = gasto_total / purchases_total if purchases_total > 0 else 0
        ctr_global = (clicks_total / impressions_total * 100) if impressions_total > 0 else 0
        cpm_global = (gasto_total / impressions_total * 1000) if impressions_total > 0 else 0
        freq_global = (impressions_total / reach_total) if reach_total > 0 else 0

        historial_diario = [
            {"fecha": f, **datos}
            for f, datos in sorted(all_daily.items())
        ]

        return {
            "gasto_total": gasto_total,
            "cuentas": cuentas,
            "cpa": cpa_total,
            "purchases_total": purchases_total,
            "historial_diario": historial_diario,
            "agregado": {
                "impressions": impressions_total,
                "reach": reach_total,
                "clicks": clicks_total,
                "ctr": ctr_global,
                "cpm": cpm_global,
                "frequency": freq_global,
                "cpc": (gasto_total / clicks_total) if clicks_total > 0 else 0,
            },
        }
