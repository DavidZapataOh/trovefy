"""Constantes técnicas de /landing (plan 18). No son umbrales de negocio: cada una lleva su fuente."""

SECCIONES_MIN = 14  # §4.8: la landing tiene 14–16 secciones
SECCIONES_MAX = 16  # §4.8
VIEWPORTS = {"movil": (390, 844), "escritorio": (1280, 800)}  # §4.8: QA en 390 y 1280 px
LCP_MAX_MS = 2500  # §4.8: LCP < 2,5 s en 4G simulado
# «4G simulado» = Slow 4G de Lighthouse (constants.js, throttling.mobileSlow4G: 150 ms RTT, 1,6·1024 kbit/s
# bajada, 750 kbit/s subida) con el ajuste de DevTools para throttling por CDP (throttling.devtools: latencia
# ×3,75 y caudal ×0,9), porque aquí se limita la red del navegador, no se simula (ruling M1).
LATENCIA_MS = 562.5  # 150 × 3,75
BAJADA_BPS = 1_474_560  # 1,6 × 1024 × 1000 × 0,9 bit/s
SUBIDA_BPS = 675_000  # 750 × 1000 × 0,9 bit/s
CPU_X = 4
DPR_MOVIL = 2  # ruling M1: móvil con is_mobile=True y device scale factor 2
RONDAS_LCP = 3  # mediana de tres medidas: una sola es ruidosa
TOLERANCIA_HITO = 0.10  # fracción del alto de página (plan 18, Tarea 6)
ANCHOS_IMAGEN = (480, 960)  # srcset: móvil 390 px a 1x–2x y escritorio a ~1x (plan 18)
TIMEOUT_ORDEN_S = 120  # tope por orden externa (pdfinfo, pdftoppm, ffmpeg)
ESTADOS_LANDING = ("producido", "con_landing", "con_checkout", "listo")  # contrato 3: desde producido
# Hosts de Meta (ruling I-4): la QA los aborta sin contarlos en las dos rutas (una QA nunca manda eventos a Meta)
# y la sonda no los anota como hosts de la tienda. Un «.» delante = ese dominio y todos sus subdominios.
HOSTS_META = (".facebook.com", ".facebook.net", ".fbcdn.net", ".fbsbx.com", ".instagram.com")


def casa_host(host: str, reglas) -> bool:
    """¿`host` casa con alguna regla? `".x.test"` = `x.test` y sus subdominios; si no, el host exacto."""
    h = (host or "").strip().lower().rstrip(".")
    for r in reglas:
        r = r.strip().lower().rstrip(".")
        if (r.startswith(".") and (h == r[1:] or h.endswith(r))) or h == r:
            return True
    return False
