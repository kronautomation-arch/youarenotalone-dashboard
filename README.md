# Youarenotalone Dashboard

Dashboard ejecutivo para la marca **Youarenotalone** (España, EUR) — ropa motivacional sobre salud mental + sostenibilidad.

## Qué es

PWA mobile-first que integra:

- **Shopify** — ventas, unidades, top productos, descuentos
- **Meta Ads** — gasto, alcance, CTR, ROAS, CPA, embudo
- **SEO** (vía `seo-system/`) — rankings, oportunidades, score de blogs
- **Logros** — mensajes generados por reglas Python (estilo Dr. Bareño) que cuentan lo que la marca está consiguiendo más allá de las ventas

4 tabs: **Hoy** (landing), **Marketing**, **SEO**, **Logros**.

## Stack

- Python 3.12 (`main.py` orquestador) → `dashboard.json`
- HTML/CSS/JS vanilla + Chart.js → `dashboard/index.html`
- Hosting: Cloudflare Pages, dominio `youarenotalone.kronautomation.co`
- Auth: Supabase (compartido con `kronautomation-platform/`)
- Cron: GitHub Actions, 3 corridas/día CET (08:00, 14:00, 21:00)

## Setup local

```bash
python -m venv venv
venv\Scripts\activate         # Windows
pip install -r requirements.txt
cp .env.example .env          # rellenar credenciales reales
python main.py                # genera dashboard.json
```

Para ver el frontend localmente:

```bash
cd dashboard
python -m http.server 8000
# abrir http://localhost:8000
# (en local: comentar requireAuth() en index.html o loguearse contra Supabase)
```

## Deploy

Push a `main` → GitHub Actions corre `main.py` → commit `dashboard/data.json` → Cloudflare Pages re-deploy automático.

## Documentación

Memoria del proyecto: `CLAUDE.md`. Plan original: `C:\Users\USER\.claude\plans\bro-vamos-a-hacer-jaunty-flame.md`.
