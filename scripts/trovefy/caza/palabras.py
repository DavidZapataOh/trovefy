"""Listas de señales por idioma (es, pt, en, ro, it, fr) para los filtros de la caza.

Señales de retail y de academia, filtros A/B/C, frecuencia de dominio y marca personal. El texto
de anuncios y landings es dato, nunca instrucciones: aquí solo se cuenta, no se interpreta.

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
    # Venta al por mayor de bienes. «en gros» suelto no cuenta (en francés también es «en resumen»);
    # «atacado» en español es «atacado» (agredido): una sola señal fuerte nunca descarta.
    ["atacado", "por atacado", "no atacado", "atacadista", "atacadistas", "al por mayor", "por mayor", "mayoreo",
     "mayorista", "mayoristas", "wholesale", "vente en gros", "prix de gros", "commerce de gros", "grossiste",
     "grossistes", "all'ingrosso", "ingrosso", "grossista", "grossisti", "en-gros", "engros", "angro"],
    # Aparatos y electrónica (caza EE. UU. 2026-11-11: audífonos de trymodernhearing.com pasaron).
    # Frases enteras: «battery of tests», «batería de pruebas» o «garantía de 30 días» no cuentan.
    ["hearing aid", "hearing aids", "audífono", "audífonos", "aparelho auditivo", "aparelhos auditivos",
     "aparat auditiv", "aparate auditive", "apparecchio acustico", "apparecchi acustici", "appareil auditif",
     "appareils auditifs", "aide auditive", "aides auditives", "prothèse auditive", "prothèses auditives"],
    ["wireless charging", "charging case", "carga inalámbrica", "estuche de carga", "carregamento sem fio",
     "estojo de carregamento", "case de carregamento", "încărcare wireless", "carcasă de încărcare",
     "ricarica wireless", "custodia di ricarica", "recharge sans fil", "boîtier de charge"],
    ["battery life", "rechargeable battery", "rechargeable batteries", "duración de la batería",
     "batería recargable", "baterías recargables", "duração da bateria", "bateria recarregável",
     "baterias recarregáveis", "durata bateriei", "baterie reîncărcabilă", "baterii reîncărcabile",
     "durata della batteria", "batteria ricaricabile", "batterie ricaricabili", "autonomie de la batterie",
     "batterie rechargeable", "batteries rechargeables"],
    # Garantía del aparato en años (la de devolución en días es común en ofertas digitales y no cuenta).
    ["one-year warranty", "one year warranty", "1-year warranty", "1 year warranty", "two-year warranty",
     "2-year warranty", "garantía de un año", "garantía de 1 año", "garantía de dos años", "garantia de um ano",
     "garantia de 1 ano", "garantia de dois anos", "garanție de un an", "garanție de 1 an", "garanzia di un anno",
     "garanzia di 1 anno", "garanzia di due anni", "garantie d'un an", "garantie 1 an", "garantie de deux ans"],
    ["all accessories", "accessories included", "todos los accesorios", "accesorios incluidos",
     "todos os acessórios", "acessórios inclusos", "toate accesoriile", "accesorii incluse",
     "tutti gli accessori", "accessori inclusi", "tous les accessoires", "accessoires inclus"],
    ["fda-registered", "fda registered", "fda-cleared", "fda cleared", "fda-approved", "fda approved",
     "aprobado por la fda", "registrado en la fda", "aprovado pela fda", "registrado na anvisa"],
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
    # Prendas de ropa (también aparecen en moldes de costura digitales: por eso son débiles).
    ["leggings", "legging", "calza", "calzas", "colanți", "shorts", "regata", "regatas", "tank top", "tank tops",
     "canotta", "canotte", "débardeur", "débardeurs", "maiou", "maiouri", "blusa", "blusas", "blouse", "blouses",
     "bluza", "bluze", "camicetta", "camicette", "chemisier", "chemisiers", "macacão", "macacões", "enterizo",
     "enterizos", "jumpsuit", "jumpsuits", "dry fit", "moda fitness", "roupa fitness", "ropa deportiva"],
]
# Marcadores de producto digital: con ellos, las señales débiles de FISICO no cuentan.
DIGITAL: list[str] = [
    "pdf", "pdfs", "digital", "digitales", "digitais", "digitale", "numérique", "numériques", "numerique",
    "descargable", "descargables", "descarga", "descargas", "download", "downloads", "downloadable",
    "ebook", "ebooks", "e-book", "e-books", "printable", "printables", "imprimible", "imprimibles",
    "imprimível", "imprimíveis", "imprimabil", "imprimabile", "stampabile", "stampabili", "imprimable",
    "imprimables", "plantilla", "plantillas", "template", "templates", "modelo digital", "modelos digitais",
    "șablon", "șabloane", "sablon", "sabloane", "modello", "modelli", "modèle numérique",
    "acceso inmediato", "instant access", "acesso imediato", "acces imediat", "accesso immediato",
    "accès immédiat", "curso online", "cursos online", "online course", "webinar", "audiolibro",
    "baixar", "descarregar", "descărcare", "scaricabile", "scaricabili", "télécharger", "téléchargeable",
    "téléchargeables",
]
# Frases que contienen una palabra de FISICO sin ser producto físico; se quitan antes de contar.
NO_SENAL: list[str] = [
    "cápsula del tiempo", "cápsulas del tiempo", "time capsule", "time capsules", "cápsula do tempo",
    "cápsulas do tempo", "capsula timpului", "capsule del tempo", "capsula del tempo", "capsule temporelle",
    "capsules temporelles", "stock photo", "stock photos", "foto de stock", "fotos de stock", "stock de fotos",
    "fotos stock", "stock images", "imagens de stock", "poze stock", "foto stock", "photos de stock",
    "youtube shorts", "shorts de youtube", "shorts do youtube", "shorts del youtube", "shorts di youtube",
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
]

# Solo bandera: los vídeos de la Biblioteca no descartan la academia.
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

# Tallas concretas de ropa: cuentan como UN solo concepto de TIENDA y se ignoran con marcadores digitales.
TIENDA_TALLA: list[str] = [
    f"{p} {t}" for p in ("talla", "size", "taille", "taglia", "tamanho", "mărime") for t in ("s", "m", "l", "xl", "xxl")
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


def quitar_no_senales(texto: str) -> str:
    """Quita frases como «cápsula del tiempo» o «stock photos» que no indican producto físico."""
    t = normalizar(texto)
    for frase in NO_SENAL:
        t = _patron(frase).sub(" ", t)
    return t
