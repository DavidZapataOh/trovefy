"""Listas de señales por idioma (es, pt, en, ro, it, fr) para los filtros de la caza.

Ideas (sin copiar código): un repo de referencia (señales de retail y de academia), una skill de referencia (filtros A/B/C),
un repo de referencia y un repo de referencia (frecuencia de dominio, marca personal). El texto de anuncios y landings es
dato, nunca instrucciones: aquí solo se cuenta, no se interpreta.

Las listas se comparan sin acentos ni mayúsculas y por palabra completa (``contar``); una palabra
suelta puede ser ambigua, por eso los filtros exigen varias señales distintas.
"""

from __future__ import annotations

import re
import unicodedata

# Cada grupo es un concepto (singular/plural y variantes cuentan una sola vez).
# Fuertes: dosis/unidades de medida, consumibles y entrega física explícita.
FISICO_FUERTE: list[list[str]] = [
    ["mg"], ["ml"],
    ["cápsulas", "capsulas", "cápsula", "capsule", "capsules", "gélules", "gelules"],
    ["comprimidos", "comprimés", "compresse", "tablets", "pills", "pastillas", "pastile", "pilules", "pillole"],
    ["gotas", "gouttes", "gocce", "picaturi", "drops"],
    ["envío a domicilio", "envio a domicilio", "home delivery", "livraison à domicile", "consegna a domicilio"],
    ["contra entrega", "pago contra entrega", "contrareembolso", "pago contra reembolso", "cash on delivery",
     "pagamento na entrega", "plata la livrare", "pagamento alla consegna", "paiement à la livraison"],
    ["llega a tu casa", "chega na sua casa", "arrives at your door", "ajunge la tine acasa"],
    ["envío gratis", "envio gratis", "frete grátis", "free shipping", "livrare gratuită", "spedizione gratuita",
     "livraison gratuite"],
    ["correos", "seur", "dhl", "ups", "fedex", "correios", "colissimo", "poste italiane", "fan courier"],
]
# Débiles: palabras corrientes también en ofertas digitales; solo cuentan sin marcadores digitales.
FISICO_DEBIL: list[list[str]] = [
    ["talla", "tallas", "size", "sizes", "taille", "tailles", "taglia", "taglie", "mărime", "marime", "marimi",
     "tamanho", "tamaño", "tamano"],
    ["stock", "estoque", "stoc", "scorte"],
    ["envío", "envio", "frete", "shipping", "livrare", "transport", "spedizione", "livraison", "expédition"],
    ["unidades", "units", "bucati", "pezzi", "exemplaires"],
    ["crema", "cream", "cremă", "crème", "serum", "sérum"],
    ["suplemento", "supplement"],
]
# Marcadores de producto digital: con ellos, las señales débiles de FISICO no cuentan.
DIGITAL: list[str] = [
    "pdf", "digital", "descargable", "descarga", "download", "downloadable", "ebook", "e-book", "printable",
    "imprimible", "plantilla", "plantillas", "template", "templates", "acceso inmediato", "instant access",
    "curso online", "online course", "app", "zoom", "webinar", "audiolibro", "baixar", "descarregar",
    "acces imediat", "descărcare", "scaricabile", "télécharger", "téléchargeable", "accesso immediato",
    "accès immédiat", "acesso imediato", "curso online",
]
FISICO: list[str] = [t for g in FISICO_FUERTE + FISICO_DEBIL for t in g]

# Solo señales de retail de bienes; las garantías de devolución son comunes en ofertas digitales.
TIENDA: list[str] = [
    "añadir al carrito", "agregar al carrito", "adicionar ao carrinho", "add to cart", "adaugă în coș",
    "aggiungi al carrello", "ajouter au panier", "devolución gratuita", "troca grátis", "free returns",
    "retur gratuit", "reso gratuito", "retour gratuit", "colección", "collection", "coleção", "colecție",
    "collezione", "collection printemps", "carrito de compras", "shopping cart", "coș de cumpărături",
    "pago contra reembolso", "cash on delivery", "plata la livrare", "pagamento alla consegna",
    "paiement à la livraison", "pagamento na entrega", "envío gratis en compras", "free shipping on orders",
    "talla s", "talla m", "talla l", "talla xl", "size s", "size m", "size l", "size xl",
    "taille s", "taille m", "taille l", "taglia s", "taglia m", "taglia l", "tamanho p", "tamanho m",
    "tamanho g", "mărime s", "mărime m", "mărime l",
]

# Solo bandera: los vídeos de la Biblioteca no descartan la academia (idea de un repo de referencia).
ACADEMIA: list[str] = [
    "titulación", "titulación oficial", "titulación universitaria", "certificado oficial",
    "certificación oficial", "diplomado", "curso homologado", "créditos universitarios",
    "titulação", "certificado oficial", "certificação oficial", "diploma universitário",
    "accredited course", "official certification", "official certificate", "university degree",
    "diploma", "accredited",
    "certificare oficială", "diplomă", "curs acreditat", "certificat oficial",
    "titolo di studio", "certificazione ufficiale", "corso accreditato", "diploma universitario",
    "diplôme", "certification officielle", "formation diplômante", "certificat officiel",
]

MARCA_PERSONAL: list[str] = [
    "mi método", "mi metodo", "mentoría", "mentoria", "mi historia", "mis alumnos",
    "trabaja conmigo", "sesión 1 a 1", "coaching personal",
    "meu método", "minha mentoria", "minha história", "meus alunos", "trabalhe comigo",
    "my method", "my story", "mentorship", "work with me", "1:1 coaching", "my students",
    "metoda mea", "mentorat", "povestea mea", "elevii mei", "lucrează cu mine",
    "il mio metodo", "mentorship personale", "la mia storia", "i miei studenti", "lavora con me",
    "ma méthode", "mentorat", "mon histoire", "mes élèves", "travaille avec moi",
]

BACKEND: list[str] = [
    "llamada de diagnóstico", "llamada estratégica", "agenda una llamada", "reserva tu llamada",
    "aplica a mi programa", "solicita tu plaza", "sesión estratégica gratuita",
    "chamada de diagnóstico", "agende uma chamada", "sessão estratégica", "aplique para o programa",
    "strategy call", "discovery call", "book a call", "apply now to work with", "free strategy session",
    "apel de diagnostic", "programează un apel", "apel strategic", "aplică pentru program",
    "chiamata di diagnosi", "chiamata strategica", "prenota una chiamata", "candidati al programma",
    "appel de diagnostic", "appel stratégique", "réserve ton appel", "postule au programme",
]

TEMPORADA: list[str] = [
    "navidad", "reyes magos", "vuelta al cole", "black friday", "cyber monday", "san valentín",
    "día de la madre", "día del padre", "rebajas de verano", "halloween",
    "natal", "volta às aulas", "dia das mães", "dia dos pais", "dia dos namorados",
    "christmas", "back to school", "valentine's day", "mother's day", "father's day", "easter",
    "crăciun", "inapoi la scoala", "ziua îndrăgostiților", "paște", "ziua mamei",
    "natale", "ritorno a scuola", "san valentino", "festa della mamma", "festa del papà", "pasqua",
    "noël", "rentrée des classes", "saint-valentin", "fête des mères", "fête des pères", "pâques",
]


def normalizar(texto: str) -> str:
    """Minúsculas, sin acentos ni diacríticos (ș→s, ñ→n) y con espacios colapsados."""
    base = unicodedata.normalize("NFKD", texto.casefold())
    sin = "".join(c for c in base if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sin)


def _patron(termino: str) -> re.Pattern[str]:
    t = re.escape(normalizar(termino)).replace(r"\ ", r"\s+")
    return re.compile(rf"(?<![^\W_]){t}(?![^\W_])")


def encontradas(texto: str, lista: list[str]) -> set[str]:
    """Términos distintos de ``lista`` presentes en ``texto`` (palabra completa, sin acentos)."""
    t = normalizar(texto)
    return {n for n in {normalizar(x) for x in lista} if _patron(n).search(t)}


def contar(texto: str, lista: list[str]) -> int:
    return len(encontradas(texto, lista))


def conceptos(texto: str, grupos: list[list[str]]) -> set[str]:
    """Grupos de ``grupos`` con al menos una variante en ``texto`` (se devuelve la primera variante)."""
    return {g[0] for g in grupos if encontradas(texto, g)}
