"""
Client para la API REST Admin de Shopify, parametrizado por país/timezone.

Adaptado de reporte-marfil/tools/shopify/shopify_client.py con 2 parámetros nuevos:
- tz_offset: offset ISO 8601 de la zona horaria local (ej "+01:00" para España, "-05:00" para Colombia)
- paid_only: si True, solo cuenta órdenes con financial_status in {paid, partially_paid, authorized}
              (excluye 'pending' que en Latam suele ser COD pero en España es transferencia bancaria pendiente)

Trae datos REALES de:
- Unidades vendidas (sum de line_items.quantity)
- Precio bruto (subtotal_price + total_discounts) y neto (total_price)
- Descuentos aplicados
- Canal de venta (source_name)
- Top productos / SKUs / variantes
- Estado financiero y fulfillment

Base URL: https://{shop}.myshopify.com/admin/api/{version}/
Auth: header X-Shopify-Access-Token

Notas:
- Rate limit ~2 req/seg en plan Basic. Se respeta el header X-Shopify-Shop-Api-Call-Limit.
- Paginación: cursor-based via header Link (rel="next").
"""

import re
import time
import requests
from datetime import date, datetime, timezone, timedelta
from typing import Optional, Iterator
from collections import defaultdict


class ShopifyAPIError(Exception):
    pass


REFUNDED_STATUSES = {"refunded", "voided"}
PAID_NOW_STATUSES = {"paid", "partially_paid", "authorized"}


class ShopifyClient:
    def __init__(
        self,
        shop: str,
        access_token: str,
        api_version: str = "2025-07",
        tz_offset: str = "-05:00",
        paid_only: bool = False,
    ):
        """
        shop: subdominio (ej "youarenotalone" para youarenotalone.myshopify.com)
        access_token: token Admin API (shpat_... o shppa_...)
        tz_offset: offset ISO de la zona local (ej "+01:00" España, "-05:00" Colombia)
        paid_only: si True, solo cuenta órdenes pagadas/autorizadas (recomendado para España)
        """
        self.shop = shop
        self.api_version = api_version
        self.base_url = f"https://{shop}.myshopify.com/admin/api/{api_version}"
        self.tz_offset = tz_offset
        self.paid_only = paid_only
        self._tz = self._parse_offset(tz_offset)
        self.session = requests.Session()
        self.session.headers.update({
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    @staticmethod
    def _parse_offset(offset: str) -> timezone:
        """Parsea '+01:00' / '-05:00' a un objeto timezone."""
        sign = 1 if offset[0] == "+" else -1
        hours, minutes = offset[1:].split(":")
        delta = timedelta(hours=int(hours) * sign, minutes=int(minutes) * sign)
        return timezone(delta)

    def _request(self, method: str, url: str, params: Optional[dict] = None) -> requests.Response:
        for attempt in range(3):
            response = self.session.request(method, url, params=params, timeout=30)

            limit_header = response.headers.get("X-Shopify-Shop-Api-Call-Limit", "")
            if "/" in limit_header:
                used, total = (int(x) for x in limit_header.split("/"))
                if used >= total - 2:
                    time.sleep(1.0)

            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", "2"))
                time.sleep(retry_after)
                continue

            if not response.ok:
                detail = response.text[:500]
                raise ShopifyAPIError(
                    f"Shopify API {response.status_code} en {url} — {detail}"
                )

            return response

        raise ShopifyAPIError(f"Shopify API rate limit no recuperado tras 3 intentos en {url}")

    def _paginate_orders(self, params: dict) -> Iterator[dict]:
        url = f"{self.base_url}/orders.json"
        current_params = dict(params)

        while True:
            response = self._request("GET", url, params=current_params)
            data = response.json()
            for o in data.get("orders", []):
                yield o

            link = response.headers.get("Link", "")
            next_url = self._parse_next_link(link)
            if not next_url:
                break
            url = next_url
            current_params = None

    @staticmethod
    def _parse_next_link(link_header: str) -> Optional[str]:
        if not link_header:
            return None
        match = re.search(r'<([^>]+)>;\s*rel="next"', link_header)
        return match.group(1) if match else None

    def get_orders(self, fecha_inicio: date, fecha_fin: date) -> list[dict]:
        """
        Trae órdenes creadas entre fecha_inicio y fecha_fin (inclusive),
        usando la zona horaria configurada en self.tz_offset.
        """
        start_iso = f"{fecha_inicio.isoformat()}T00:00:00{self.tz_offset}"
        end_iso = f"{fecha_fin.isoformat()}T23:59:59{self.tz_offset}"

        params = {
            "status": "any",
            "created_at_min": start_iso,
            "created_at_max": end_iso,
            "limit": 250,
            "fields": (
                "id,name,created_at,processed_at,cancelled_at,"
                "currency,total_price,subtotal_price,total_discounts,total_tax,"
                "total_shipping_price_set,"
                "financial_status,fulfillment_status,"
                "source_name,discount_codes,discount_applications,"
                "tags,test,line_items"
            ),
        }

        return list(self._paginate_orders(params))

    def get_resumen_ventas(self, fecha_inicio: date, fecha_fin: date) -> dict:
        """
        Procesa órdenes y devuelve métricas reales.

        Reglas:
        - Cancelled (cancelled_at != null) → no cuenta como venta.
        - Refunded/voided → no cuenta.
        - Si self.paid_only=True: solo cuentan paid, partially_paid, authorized.
        - Historial diario agrupado por created_at en zona horaria self.tz_offset.
        - "Bruto" = subtotal_price + total_discounts.
        - "Neto" = total_price.
        - Unidades excluyen gift cards.
        """
        orders = self.get_orders(fecha_inicio, fecha_fin)

        ventas_brutas = 0.0
        ventas_netas = 0.0
        descuentos_total = 0.0
        unidades = 0
        ordenes_validas = 0

        canceladas_count = 0
        canceladas_monto = 0.0
        refunded_count = 0
        refunded_monto = 0.0
        unpaid_count = 0  # solo cuando paid_only=True
        unpaid_monto = 0.0

        ventas_por_dia = defaultdict(lambda: {
            "ventas_brutas": 0.0,
            "ventas_netas": 0.0,
            "descuentos": 0.0,
            "unidades": 0,
            "ordenes": 0,
        })
        productos_top = defaultdict(lambda: {"unidades": 0, "ventas": 0.0, "vendor": ""})
        skus_top = defaultdict(lambda: {"unidades": 0, "ventas": 0.0, "title": ""})
        canales = defaultdict(lambda: {"ordenes": 0, "ventas_brutas": 0.0})
        codigos_descuento = defaultdict(lambda: {"usos": 0, "monto": 0.0})

        for o in orders:
            if o.get("test"):
                continue

            cancelled_at = o.get("cancelled_at")
            financial_status = (o.get("financial_status") or "").lower()
            total_price = float(o.get("total_price") or 0)
            subtotal = float(o.get("subtotal_price") or 0)
            total_discounts = float(o.get("total_discounts") or 0)
            bruto = subtotal + total_discounts
            source = o.get("source_name") or "unknown"

            if cancelled_at:
                canceladas_count += 1
                canceladas_monto += bruto
                continue

            if financial_status in REFUNDED_STATUSES:
                refunded_count += 1
                refunded_monto += bruto
                continue

            if self.paid_only and financial_status not in PAID_NOW_STATUSES:
                unpaid_count += 1
                unpaid_monto += bruto
                continue

            ordenes_validas += 1
            ventas_brutas += bruto
            ventas_netas += total_price
            descuentos_total += total_discounts

            order_units = 0
            for li in o.get("line_items", []):
                if li.get("gift_card"):
                    continue
                qty = int(li.get("quantity") or 0)
                order_units += qty

                title = li.get("title") or "(sin título)"
                vendor = li.get("vendor") or ""
                price_li = float(li.get("price") or 0) * qty
                productos_top[title]["unidades"] += qty
                productos_top[title]["ventas"] += price_li
                productos_top[title]["vendor"] = vendor

                sku = li.get("sku") or "(sin SKU)"
                variante = li.get("variant_title") or ""
                sku_key = f"{sku} - {variante}".strip(" -") if variante else sku
                skus_top[sku_key]["unidades"] += qty
                skus_top[sku_key]["ventas"] += price_li
                skus_top[sku_key]["title"] = title

            unidades += order_units

            fecha_dia = self._parse_fecha_local(o.get("created_at", ""))
            fecha_key = fecha_dia.isoformat() if fecha_dia else None
            if fecha_key:
                d = ventas_por_dia[fecha_key]
                d["ventas_brutas"] += bruto
                d["ventas_netas"] += total_price
                d["descuentos"] += total_discounts
                d["unidades"] += order_units
                d["ordenes"] += 1

            canales[source]["ordenes"] += 1
            canales[source]["ventas_brutas"] += bruto

            for dc in o.get("discount_codes", []):
                code = dc.get("code") or "(sin código)"
                amount = float(dc.get("amount") or 0)
                codigos_descuento[code]["usos"] += 1
                codigos_descuento[code]["monto"] += amount

        top_productos = sorted(
            [{"nombre": k, **v} for k, v in productos_top.items()],
            key=lambda x: x["unidades"], reverse=True,
        )[:15]
        top_skus = sorted(
            [{"sku": k, **v} for k, v in skus_top.items()],
            key=lambda x: x["unidades"], reverse=True,
        )[:20]
        canales_list = sorted(
            [{"canal": k, **v} for k, v in canales.items()],
            key=lambda x: x["ventas_brutas"], reverse=True,
        )
        codigos_list = sorted(
            [{"codigo": k, **v} for k, v in codigos_descuento.items()],
            key=lambda x: x["monto"], reverse=True,
        )[:15]

        historial_diario = [
            {"fecha": fecha, **datos}
            for fecha, datos in sorted(ventas_por_dia.items())
        ]

        return {
            "ventas_brutas": round(ventas_brutas, 2),
            "ventas_netas": round(ventas_netas, 2),
            "descuentos_total": round(descuentos_total, 2),
            "unidades": unidades,
            "ordenes": ordenes_validas,
            "canceladas": {
                "ordenes": canceladas_count,
                "monto": round(canceladas_monto, 2),
            },
            "reembolsadas": {
                "ordenes": refunded_count,
                "monto": round(refunded_monto, 2),
            },
            "no_pagadas": {
                "ordenes": unpaid_count,
                "monto": round(unpaid_monto, 2),
                "nota": "Excluidas porque paid_only=True (financial_status no era paid/partially_paid/authorized)" if self.paid_only else None,
            },
            "historial_diario": historial_diario,
            "top_productos": top_productos,
            "top_skus": top_skus,
            "canales": canales_list,
            "codigos_descuento": codigos_list,
        }

    def _parse_fecha_local(self, iso_str: str) -> Optional[date]:
        """
        Parsea fecha ISO 8601 de Shopify y devuelve la fecha en la zona local
        configurada en self.tz_offset.
        """
        if not iso_str:
            return None
        try:
            dt = datetime.fromisoformat(iso_str)
            if dt.tzinfo is not None:
                dt = dt.astimezone(self._tz)
            return dt.date()
        except (ValueError, TypeError):
            return None
