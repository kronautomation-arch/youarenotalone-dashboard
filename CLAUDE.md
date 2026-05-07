# CLAUDE.md — Youarenotalone Dashboard

## Contexto

Dashboard ejecutivo para **Youarenotalone**, marca española de ropa motivacional sobre salud mental + sostenibilidad. Vende por Shopify, hace ads en Meta, tiene SEO orgánico.

Stack idéntico a Marfil/Bareño con 3 diferencias clave:
- País España (EUR, CET) en lugar de Colombia (COP, COT)
- Sin courier cross-check (España es 100% prepago)
- Sección de Logros con reglas Python al estilo Bareño

## Arquitectura WAT Framework

- **TOOLS** — scripts Python deterministas en `tools/`:
  - `tools/core/` — env_loader, logger
  - `tools/shopify/shopify_client.py` — copia de Marfil parametrizada con `tz_offset` y `paid_only`
  - `tools/meta/meta_client.py` — copia exacta de Marfil
  - `tools/seo/loader.py` — adapta `_load_seo_section()` de Marfil al path `seo-system/output/youarenotalone/`
  - `tools/achievements/rules.py` — 20 reglas que generan los mensajes de logros
- **AGENT** — `main.py` orquesta el pipeline (sin Claude, todo determinista)
- **OUTPUT** — `dashboard.json` (raíz) y `dashboard/data.json` (publicado)

## Flujo

1. `main.py` lee Shopify YTD + Meta YTD
2. Construye `daily` (un objeto por día con ventas/meta combinados)
3. Carga SEO desde `../seo-system/output/youarenotalone/`
4. Genera 4 slices (hoy/semana/mes/ytd) y aplica las 20 reglas → `logros`
5. Vuelca todo a `dashboard.json` y copia a `dashboard/data.json`
6. Frontend `dashboard/index.html` hace `fetch('data.json')` y renderiza 4 tabs

## Hosting

- Subdominio: `youarenotalone.kronautomation.co`
- Cloudflare Pages conectado a `main`, build folder `dashboard/`
- Auth: Supabase (key/URL en `dashboard/auth.js`, compartido con kronautomation-platform). Crear usuario en `app_users` con `project='youarenotalone'`
- Cron: 3 corridas/día CET (08:00, 14:00, 21:00) vía `.github/workflows/update-data.yml`

## SEO multi-tenant

Stores en `seo-system/config/stores.json`. Activado youarenotalone con:
- `country_code: 2724` (España)
- `language: "es"`
- `platform: "shopify"`
- Domain: `youarenotalone.es` (confirmar con usuario el dominio definitivo)

Para correr keyword research + auditoría:
```bash
cd ../seo-system
python agent.py --store youarenotalone
```

Genera `seo-system/output/youarenotalone/reports/seo_dashboard.json` que el dashboard consume.

## Comandos útiles

```bash
python main.py                       # genera dashboard.json
run_manual.bat                       # idem en Windows con venv activado
cd dashboard && python -m http.server 8000   # frontend local
```

## Cosas que el usuario debe entregar

Ver sección K del plan original en `C:\Users\USER\.claude\plans\bro-vamos-a-hacer-jaunty-flame.md`.
