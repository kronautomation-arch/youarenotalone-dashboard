"""
20 reglas Python que generan los mensajes de logros del dashboard.

Cada regla recibe métricas de un período (hoy / esta semana / este mes / ytd)
más un label contextual y devuelve un string (o None si no aplica).

Tono: español de España, cálido y motivacional, evitando trivializar la salud
mental. Mezcla de logros de marketing, ventas y SEO.

La función pública es generar_logros(slice_data, period_label) que aplica
todas las reglas y devuelve la lista de mensajes filtrada.
"""

from typing import Optional


# ──────────────────────────────────────────────────────────────────────────
# Helpers de formato (español España: separador de miles ".", decimal ",")
# ──────────────────────────────────────────────────────────────────────────

def _eur(n: float) -> str:
    return f"{int(round(n)):,}".replace(",", ".") + " €"


def _num(n: float) -> str:
    return f"{int(round(n)):,}".replace(",", ".")


def _pct(x: float, decimals: int = 1) -> str:
    return f"{x:.{decimals}f}".replace(".", ",") + "%"


def _f(x: float, decimals: int = 1) -> str:
    return f"{x:.{decimals}f}".replace(".", ",")


# ──────────────────────────────────────────────────────────────────────────
# Grupo 1 — Alcance & Marca (Meta)
# ──────────────────────────────────────────────────────────────────────────

def regla_personas_alcanzadas(reach: int, period: str) -> Optional[str]:
    if reach <= 0:
        return None
    if reach < 500:
        return f"💜 {period.capitalize()} {_num(reach)} personas han visto un mensaje de que no están solas. Cada una cuenta."
    if reach < 10000:
        return f"💜 {period.capitalize()} hemos llegado a {_num(reach)} personas en España — {_num(reach)} corazones que recibieron el mensaje."
    return f"💜 {_num(reach)} personas alcanzadas {period}. Toda una ciudad pequeña sabiendo que hay alguien al otro lado."


def regla_impresiones(impressions: int, period: str) -> Optional[str]:
    if impressions < 5000:
        return None
    if impressions < 50000:
        return f"👁️ {_num(impressions)} impresiones {period} — el mensaje circula."
    return f"👁️ {_num(impressions)} veces hemos aparecido en pantalla {period}. La conversación sobre salud mental no se detiene."


def regla_frecuencia(frequency: float, period: str) -> Optional[str]:
    if frequency <= 0:
        return None
    if frequency < 2:
        return f"🌱 Frecuencia {_f(frequency)}x — seguimos abriendo puertas a personas nuevas."
    if frequency <= 4:
        return f"✨ Frecuencia {_f(frequency)}x — el punto justo: la marca se queda en la memoria sin saturar."
    return f"🤝 Frecuencia {_f(frequency)}x — quienes ya nos conocen no nos olvidan. Comunidad sólida."


def regla_ctr(ctr: float, period: str) -> Optional[str]:
    if ctr <= 0:
        return None
    if ctr < 1:
        return f"📊 CTR {_pct(ctr, 2)} — pocos clics aún, pero quien clica viene buscando algo real."
    if ctr < 2.5:
        return f"📊 CTR {_pct(ctr, 2)} — hay gente parándose a leer el mensaje. Buena señal."
    return f"🎯 CTR {_pct(ctr, 2)} — uno de cada {int(100/ctr)} que ven el anuncio quiere saber más. Conexión auténtica."


def regla_clicks(clicks: int, period: str) -> Optional[str]:
    if clicks <= 0:
        return None
    if clicks < 100:
        return f"🖱️ {_num(clicks)} personas han querido entrar y leer {period}."
    if clicks < 1000:
        return f"🖱️ {_num(clicks)} clics {period} — {_num(clicks)} curiosos que dieron el paso."
    return f"🖱️ {_num(clicks)} clics {period} — el mensaje resuena fuerte."


# ──────────────────────────────────────────────────────────────────────────
# Grupo 2 — Conversión & Ventas (Shopify)
# ──────────────────────────────────────────────────────────────────────────

def regla_unidades_vendidas(unidades: int, period: str) -> Optional[str]:
    if unidades <= 0:
        return None
    if unidades <= 10:
        return f"🌟 {_num(unidades)} prendas vendidas {period} — {_num(unidades)} personas hoy llevan puesto un recordatorio de que importan."
    if unidades <= 50:
        return f"🌟 {_num(unidades)} prendas {period} — {_num(unidades)} historias caminando por ahí con el mensaje."
    return f"🌟 {_num(unidades)} prendas {period}. {_num(unidades)} pequeños recordatorios de que no estás solo, repartidos por España."


def regla_ventas_netas(ventas: float, period: str) -> Optional[str]:
    if ventas <= 0:
        return None
    if ventas < 1000:
        return f"💶 {_eur(ventas)} {period} — cada euro sostiene la causa."
    if ventas < 10000:
        return f"💶 {_eur(ventas)} facturados {period}. La marca camina."
    return f"💶 {_eur(ventas)} {period}. Cada compra es un voto a favor de hablar de salud mental sin tabúes."


def regla_ordenes(ordenes: int, period: str) -> Optional[str]:
    if ordenes <= 0:
        return None
    if ordenes <= 20:
        return f"🛍️ {_num(ordenes)} pedidos {period} — {_num(ordenes)} decisiones de unirse."
    return f"🛍️ {_num(ordenes)} pedidos {period}. {_num(ordenes)} personas que han decidido formar parte."


def regla_ticket_promedio(ticket: float) -> Optional[str]:
    if ticket <= 0:
        return None
    if ticket < 30:
        return f"🎫 Ticket promedio {_eur(ticket)} — accesible, como queremos que sea."
    if ticket <= 60:
        return f"🎫 Ticket {_eur(ticket)} — la gente se lleva más de una pieza, lo que hace circular el mensaje aún más."
    return f"🎫 Ticket {_eur(ticket)} — la comunidad apuesta fuerte por la marca."


def regla_top_producto(top_productos: list, period: str) -> Optional[str]:
    if not top_productos:
        return None
    top = top_productos[0]
    nombre = top.get("nombre", "")
    unidades = top.get("unidades", 0)
    if unidades <= 0:
        return None
    return f"👑 La prenda más querida {period}: «{nombre}» con {_num(unidades)} unidades. Esa frase está conectando."


def regla_descuento_aplicado(tasa_descuento: float) -> Optional[str]:
    if tasa_descuento <= 0:
        return None
    pct_value = tasa_descuento * 100
    if pct_value < 5:
        return f"🎟️ Descuentos en sólo {_pct(pct_value)} de las ventas — los clientes vienen por la marca, no por la oferta."
    if pct_value <= 15:
        return f"🎟️ {_pct(pct_value)} en descuentos — equilibrio sano entre captación y margen."
    return f"🎟️ {_pct(pct_value)} en descuentos — empuje fuerte de promociones, ojo con el margen."


# ──────────────────────────────────────────────────────────────────────────
# Grupo 3 — Eficiencia & Finanzas (Meta × Shopify)
# ──────────────────────────────────────────────────────────────────────────

def regla_roas(roas: float, gasto_meta: float, period: str) -> Optional[str]:
    if gasto_meta <= 0:
        return None
    if roas < 1:
        return f"📉 ROAS {_f(roas)}x {period} — invertimos más de lo que vuelve. Toca revisar creatividades o segmentación."
    if roas < 2:
        return f"📊 ROAS {_f(roas)}x — la inversión se sostiene, pero hay margen para crecer."
    if roas < 4:
        return f"📈 ROAS {_f(roas)}x: por cada euro invertido, {_f(roas)} € regresan al proyecto. La causa se sostiene."
    return f"🚀 ROAS {_f(roas)}x — cada euro multiplica. La marca está en su mejor momento."


def regla_cpa(cpa: float, ticket_promedio: float) -> Optional[str]:
    if cpa <= 0 or ticket_promedio <= 0:
        return None
    ratio = cpa / ticket_promedio
    if ratio < 0.3:
        return f"💎 CPA {_eur(cpa)} sobre un ticket de {_eur(ticket_promedio)} — adquirir clientes nuevos cuesta una fracción de lo que dejan."
    if ratio < 0.6:
        return f"💰 CPA {_eur(cpa)} — sano, pero podemos optimizar para que cada nuevo cliente cueste menos."
    return f"⚠️ CPA {_eur(cpa)} cerca o sobre el ticket {_eur(ticket_promedio)} — captar nuevos clientes está saliendo caro. Toca revisar."


def regla_purchases_meta(purchases_meta: int, ordenes_shopify: int, period: str) -> Optional[str]:
    if purchases_meta <= 0:
        return None
    if ordenes_shopify <= 0:
        return f"🎯 Meta atribuye {_num(purchases_meta)} compras {period}, pero Shopify aún no las refleja — revisar el píxel."
    coincidencia = min(purchases_meta, ordenes_shopify) / max(purchases_meta, ordenes_shopify) * 100
    return f"🎯 Meta atribuye {_num(purchases_meta)} compras {period}; Shopify confirma {_num(ordenes_shopify)} pedidos. Coincidencia del {_pct(coincidencia, 0)}, los anuncios traen ventas reales."


def regla_inversion_publicitaria(gasto_meta: float, period: str) -> Optional[str]:
    if gasto_meta <= 0:
        return None
    if gasto_meta < 300:
        return f"💸 {_eur(gasto_meta)} en publicidad {period} — inversión cuidada."
    if gasto_meta < 2000:
        return f"💸 {_eur(gasto_meta)} en Meta {period} — sembrando audiencia."
    return f"💸 {_eur(gasto_meta)} en publicidad {period}. Apuesta seria por hacer crecer el alcance del mensaje."


# ──────────────────────────────────────────────────────────────────────────
# Grupo 4 — SEO & Contenido (seo-system)
# ──────────────────────────────────────────────────────────────────────────

def regla_keywords_top10(rankings: list) -> Optional[str]:
    if not rankings:
        return None
    top10 = sum(1 for r in rankings if r.get("position", 999) <= 10)
    if top10 == 0:
        return None
    if top10 == 1:
        return "🔎 1 palabra clave nuestra ya aparece en la primera página de Google. La gente nos encuentra."
    if top10 <= 5:
        return f"🔎 {_num(top10)} palabras clave nuestras aparecen en la primera página de Google. La gente nos encuentra."
    if top10 <= 20:
        return f"🔎 {_num(top10)} keywords en top 10 — la marca empieza a tener presencia orgánica seria."
    return f"🔎 {_num(top10)} keywords en top 10. Cada búsqueda es una nueva persona que nos descubre sin pagar un anuncio."


def regla_score_blog(audit_summary: dict) -> Optional[str]:
    if not audit_summary:
        return None
    avg = audit_summary.get("avg_score", 0)
    n = audit_summary.get("total_articles", 0)
    if avg <= 0 or n <= 0:
        return None
    if avg < 60:
        return f"📝 Score blog {_f(avg)}/100 sobre {_num(n)} artículos — hay margen importante para optimizar contenido."
    if avg < 80:
        return f"📝 Score blog {_f(avg)}/100 sobre {_num(n)} artículos — sólido, mejorable."
    return f"📝 Score blog {_f(avg)}/100 — el contenido está al nivel de medios de salud mental establecidos."


def regla_oportunidades_seo(top_opportunities: list) -> Optional[str]:
    if not top_opportunities:
        return None
    n = len(top_opportunities)
    volumen = sum(o.get("volume", 0) for o in top_opportunities)
    if volumen <= 0:
        return None
    return f"🌱 {_num(n)} oportunidades de keywords detectadas con {_num(volumen)} búsquedas/mes sin atender. Cada una es un blog que conectaría con alguien que está buscando ayuda."


def regla_mejora_score(progress: dict) -> Optional[str]:
    if not progress:
        return None
    pct = progress.get("improvement_pct", 0)
    if pct == 0:
        return None
    if pct > 0:
        return f"📈 Score subió {_pct(pct)} desde el inicio — el trabajo SEO se está notando."
    return f"📉 Score bajó {_pct(abs(pct))} — toca auditar qué pasó."


def regla_clics_organicos_estimados(projections: dict) -> Optional[str]:
    if not projections:
        return None
    clicks = projections.get("current_estimated_clicks_per_month", 0)
    if clicks <= 0:
        return None
    if clicks < 100:
        return f"🌐 ~{_num(clicks)} visitas orgánicas/mes estimadas. Tráfico que no cuesta y ya está sembrado."
    return f"🌐 ~{_num(clicks)} visitas orgánicas/mes. Cada mes alguien busca algo y nos encuentra."


# ──────────────────────────────────────────────────────────────────────────
# Función orquestadora
# ──────────────────────────────────────────────────────────────────────────

def generar_logros(slice_data: dict, period_label: str, seo: Optional[dict] = None) -> dict:
    """
    Aplica las 20 reglas y devuelve mensajes agrupados por categoría.

    slice_data: dict con keys:
        meta:     {reach, impressions, frequency, ctr, clicks, gasto, purchases}
        shopify:  {ventas_netas, ventas_brutas, descuentos, unidades, ordenes,
                   ticket_promedio, top_productos, tasa_descuento}
        roas:     float (calculado en main.py)
        cpa:      float

    period_label: string descriptivo del período ("hoy", "esta semana", etc.)
                  En "ytd" usar "este año" para que las frases lean mejor.
    seo:          dict opcional con audit_summary, current_rankings,
                  top_opportunities, progress, projections (solo se aplica una
                  vez con datos globales — no varía por período).

    Retorna:
    {
        "alcance":    [strings...],
        "ventas":     [strings...],
        "eficiencia": [strings...],
        "seo":        [strings...],
        "all":        [strings...]   # plana, todos los mensajes en orden
    }
    """
    meta = slice_data.get("meta", {})
    shopify = slice_data.get("shopify", {})

    # Grupo 1
    alcance = [
        regla_personas_alcanzadas(meta.get("reach", 0), period_label),
        regla_impresiones(meta.get("impressions", 0), period_label),
        regla_frecuencia(meta.get("frequency", 0), period_label),
        regla_ctr(meta.get("ctr", 0), period_label),
        regla_clicks(meta.get("clicks", 0), period_label),
    ]

    # Grupo 2
    ventas = [
        regla_unidades_vendidas(shopify.get("unidades", 0), period_label),
        regla_ventas_netas(shopify.get("ventas_netas", 0), period_label),
        regla_ordenes(shopify.get("ordenes", 0), period_label),
        regla_ticket_promedio(shopify.get("ticket_promedio", 0)),
        regla_top_producto(shopify.get("top_productos", []), period_label),
        regla_descuento_aplicado(shopify.get("tasa_descuento", 0)),
    ]

    # Grupo 3
    eficiencia = [
        regla_roas(slice_data.get("roas", 0), meta.get("gasto", 0), period_label),
        regla_cpa(slice_data.get("cpa", 0), shopify.get("ticket_promedio", 0)),
        regla_purchases_meta(meta.get("purchases", 0), shopify.get("ordenes", 0), period_label),
        regla_inversion_publicitaria(meta.get("gasto", 0), period_label),
    ]

    # Grupo 4 — SEO solo si está disponible
    seo_msgs = []
    if seo:
        seo_msgs = [
            regla_keywords_top10(seo.get("current_rankings", [])),
            regla_score_blog(seo.get("audit_summary", {})),
            regla_oportunidades_seo(seo.get("top_opportunities", [])),
            regla_mejora_score(seo.get("progress", {})),
            regla_clics_organicos_estimados(seo.get("projections", {})),
        ]

    def _clean(lst):
        return [m for m in lst if m]

    alcance_c = _clean(alcance)
    ventas_c = _clean(ventas)
    eficiencia_c = _clean(eficiencia)
    seo_c = _clean(seo_msgs)

    return {
        "alcance": alcance_c,
        "ventas": ventas_c,
        "eficiencia": eficiencia_c,
        "seo": seo_c,
        "all": alcance_c + ventas_c + eficiencia_c + seo_c,
    }
