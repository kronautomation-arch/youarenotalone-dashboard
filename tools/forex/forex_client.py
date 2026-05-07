"""
Conversión de divisas con tasas históricas diarias.

Fuente: fawazahmed0/exchange-api (gratis, sin API key, soporta COP y todas
las divisas, histórico desde 2024).

URL diaria: https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{date}/v1/currencies/{from}.json
Fallback:   https://{date}.currency-api.pages.dev/v1/currencies/{from}.json

Devuelve la tasa de "1 unidad de from" → "X unidades de to". Ej: 1 COP = 0.000234 EUR.

Cachea localmente en .tmp/forex_cache.json para no rehacer requests entre
corridas. Si una fecha está en cache, no la pide de nuevo.

Notas:
- Para fechas muy recientes (hoy mismo) la API puede tener delay; si falla,
  reintenta con la fecha del día anterior.
- Para fines de semana / festivos no hay tasa nueva — la API devuelve la
  tasa del último día hábil. Eso está bien para nuestro caso.
"""

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

import requests


CACHE_PATH = Path(__file__).resolve().parent.parent.parent / ".tmp" / "forex_cache.json"
PRIMARY_URL = "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{date}/v1/currencies/{base}.json"
FALLBACK_URL = "https://{date}.currency-api.pages.dev/v1/currencies/{base}.json"


def _load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def _fetch_rate(d: date, base: str, target: str) -> float | None:
    """Llama a la API y devuelve la tasa base→target para un día concreto."""
    base_lower = base.lower()
    target_lower = target.lower()
    date_str = d.isoformat()

    for url_template in (PRIMARY_URL, FALLBACK_URL):
        url = url_template.format(date=date_str, base=base_lower)
        try:
            r = requests.get(url, timeout=15)
            if r.status_code == 200:
                data = r.json()
                rate = data.get(base_lower, {}).get(target_lower)
                if rate is not None:
                    return float(rate)
        except (requests.RequestException, json.JSONDecodeError):
            continue
    return None


def get_daily_rates(
    base: str,
    target: str,
    start: date,
    end: date,
    logger=None,
) -> dict[str, float]:
    """
    Devuelve un dict {YYYY-MM-DD: rate} con la tasa base→target para cada
    día del rango [start, end] inclusive.

    Cachea cada día consultado. Si la API falla para un día puntual, usa
    la tasa del día anterior disponible en cache (forward-fill).
    """
    if base.upper() == target.upper():
        # Misma moneda, tasa = 1.0
        return {(start + timedelta(days=i)).isoformat(): 1.0
                for i in range((end - start).days + 1)}

    cache = _load_cache()
    cache_key = f"{base.upper()}_{target.upper()}"
    if cache_key not in cache:
        cache[cache_key] = {}

    rates: dict[str, float] = {}
    last_known: float | None = None
    fetched = 0

    today = date.today()
    cur = start
    while cur <= end:
        day_str = cur.isoformat()

        # Hit de cache
        if day_str in cache[cache_key]:
            rate = cache[cache_key][day_str]
        else:
            # Fecha futura → no la consultamos
            if cur > today:
                rate = last_known
            else:
                rate = _fetch_rate(cur, base, target)
                if rate is not None:
                    cache[cache_key][day_str] = rate
                    fetched += 1
                else:
                    rate = last_known  # fallback al último conocido
                    if logger:
                        logger.warning(f"FX {base}→{target}: no rate for {day_str}, usando última conocida {rate}")

        if rate is not None:
            rates[day_str] = rate
            last_known = rate

        cur += timedelta(days=1)

    if fetched > 0:
        _save_cache(cache)
        if logger:
            logger.info(f"FX {base}→{target}: {fetched} tasas nuevas descargadas y cacheadas")

    return rates


def convert_daily(
    daily_amounts: Iterable[tuple[str, float]],
    rates: dict[str, float],
    fallback_rate: float | None = None,
) -> list[tuple[str, float]]:
    """
    Convierte una secuencia de (fecha_iso, monto) usando las rates diarias.
    Si una fecha no tiene tasa y no hay fallback, deja el monto sin convertir
    (devuelve None ahí). El llamador decide qué hacer.
    """
    out = []
    for fecha, monto in daily_amounts:
        rate = rates.get(fecha, fallback_rate)
        if rate is None:
            out.append((fecha, None))
        else:
            out.append((fecha, monto * rate))
    return out
