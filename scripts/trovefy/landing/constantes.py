"""Constantes técnicas de /landing (plan 18). No son umbrales de negocio: cada una lleva su fuente."""

SECCIONES_MIN = 14  # §4.8: la landing tiene 14–16 secciones
SECCIONES_MAX = 16  # §4.8
VIEWPORTS = {"movil": (390, 844), "escritorio": (1280, 800)}  # §4.8: QA en 390 y 1280 px
LCP_MAX_MS = 2500  # §4.8: LCP < 2,5 s en 4G simulado
# «4G simulado» = perfil Slow 4G de Lighthouse (constants.js, throttling.mobileSlow4G)
LATENCIA_MS = 150
BAJADA_BPS = 1_638_400
SUBIDA_BPS = 750_000
CPU_X = 4
RONDAS_LCP = 3  # mediana de tres medidas: una sola es ruidosa
TOLERANCIA_HITO = 0.10  # fracción del alto de página (plan 18, Tarea 6)
ANCHOS_IMAGEN = (480, 960)  # srcset: móvil 390 px a 1x–2x y escritorio a ~1x (plan 18)
TIMEOUT_ORDEN_S = 120  # tope por orden externa (pdfinfo, pdftoppm, ffmpeg)
ESTADOS_LANDING = ("producido", "con_landing", "con_checkout", "listo")  # contrato 3: desde producido
