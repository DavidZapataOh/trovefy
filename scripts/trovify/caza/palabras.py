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

FISICO: list[str] = [
    # es
    "cápsulas", "capsulas", "comprimidos", "pastillas", "gotas", "crema", "mg", "talla", "tallas",
    "envío", "stock", "unidades", "suplemento", "sérum", "serum",
    # pt
    "cápsulas", "comprimidos", "gotas", "tamanho", "frete", "estoque", "unidades", "suplemento",
    # en
    "capsules", "tablets", "pills", "drops", "cream", "size", "sizes", "shipping", "units",
    "supplement",
    # ro
    "capsule", "pastile", "picaturi", "cremă", "marime", "marimi", "livrare", "transport", "stoc", "bucati",
    # it
    "capsule", "compresse", "pillole", "gocce", "crema", "taglia", "taglie", "spedizione", "scorte", "pezzi",
    # fr
    "gélules", "gelules", "comprimés", "pilules", "gouttes", "crème", "taille", "tailles", "livraison",
    "expédition", "exemplaires",
]

TIENDA: list[str] = [
    # es
    "añadir al carrito", "agregar al carrito", "pago contra reembolso", "contrareembolso",
    "pago contra entrega", "envío gratis", "devolución gratuita", "garantía de devolución",
    # pt
    "adicionar ao carrinho", "pagamento na entrega", "frete grátis", "troca grátis",
    # en
    "add to cart", "shopping cart", "cash on delivery", "free shipping", "free returns", "money back",
    # ro
    "adaugă în coș", "coș de cumpărături", "plata la livrare", "livrare gratuită", "retur gratuit",
    # it
    "aggiungi al carrello", "pagamento alla consegna", "spedizione gratuita", "reso gratuito",
    # fr
    "ajouter au panier", "paiement à la livraison", "livraison gratuite", "retour gratuit",
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
    "mi método", "mi metodo", "mentoría", "mentoria", "mi historia", "mi programa", "mis alumnos",
    "trabaja conmigo", "sesión 1 a 1", "coaching personal",
    "meu método", "minha mentoria", "minha história", "meus alunos", "trabalhe comigo",
    "my method", "my story", "mentorship", "work with me", "1:1 coaching", "my students", "my program",
    "metoda mea", "mentorat", "povestea mea", "elevii mei", "lucrează cu mine", "programul meu",
    "il mio metodo", "mentorship personale", "la mia storia", "i miei studenti", "lavora con me",
    "ma méthode", "mentorat", "mon histoire", "mes élèves", "travaille avec moi", "mon programme",
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
