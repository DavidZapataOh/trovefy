"""Huellas de pasarelas de pago y rastreadores (§4.7).

Una entrada es ``host``, ``host/prefijo-de-ruta`` o ``*.sufijo`` (cualquier subdominio del sufijo).
"""

from __future__ import annotations

GATEWAYS: dict[str, list[str]] = {
    "hotmart": ["pay.hotmart.com", "go.hotmart.com", "hotm.art"],
    "kiwify": ["pay.kiwify.com.br", "kiwify.app"],
    "whop": ["whop.com/checkout", "whop.com/"],
    "impultienda": ["*.impultienda.ar"],
    "cartpanda": ["mycartpanda.com", "*.mycartpanda.com", "*.cartpanda.com"],
    "stripe": ["buy.stripe.com", "checkout.stripe.com"],
    "gumroad": ["gumroad.com", "*.gumroad.com"],
    "payhip": ["payhip.com"],
    "lemonsqueezy": ["*.lemonsqueezy.com", "lemonsqueezy.com/checkout"],
    "mercadopago": ["mercadopago.com", "*.mercadopago.com", "*.mercadopago.com.ar", "mpago.la", "mpago.li"],
}

# Plataformas cuya huella no se ha confirmado con tiendas reales (ver notas abajo).
POR_VERIFICAR: set[str] = {"whop", "cartpanda"}  # Impultienda quedó verificada (ver VERIFICACION)

# Rastreadores de afiliación/redirecciones: nombre -> hosts.
TRACKERS_POR_NOMBRE: dict[str, list[str]] = {
    "redtrack": ["redtrack.io", "*.rdtk.io", "*.redtrack.io"],
    "voluum": ["voluum.com", "*.voluum.com"],
    "keitaro": ["keitaro.io", "*.keitaro.io"],
    "binom": ["binom.org", "*.binom.org"],
}

TRACKERS: list[str] = [h for hosts in TRACKERS_POR_NOMBRE.values() for h in hosts]

# Verificación de las huellas «por verificar» (§4.7), con Chromium efímero móvil y sin tocar Meta:
VERIFICACION: dict[str, str] = {
    "impultienda": (
        "verificado el 2026-11-10 con 3 tiendas de palabra_impultienda.json: "
        "la tienda es el propio subdominio *.impultienda.ar (página de venta y pedido en el "
        "mismo host, sin salto a otra pasarela); una tienda borrada devuelve HTTP 404 y «Tienda no "
        "encontrada», que se trata como landing no medida; una muestra precio (17 USD) y un "
        "reproductor Wistia renderizado; las tres cargan scripts de supabase.co y del pixel de Facebook"
    ),
    "whop": (
        "no verificado (2026-11-10, ninguna tienda de Whop en las fixtures); indicio: una tienda "
        "Impultienda pide t.whop.tw (rastreo de Whop), sin enlace de checkout visible"
    ),
    "cartpanda": "no verificado (2026-11-10, ninguna tienda de Cartpanda en las fixtures)",
}
