"""Página de downsell con tragamonedas, calcada de la del vídeo (V1 1:12:50–1:13:40: «SLOT DI NATALE · UN SOLO
TENTATIVO: OGGI», «TIRA LA LEVA», rodillos de cifras que caen en «2 · 1 · %», «21% OFF», precio tachado, «Risparmi»,
botón rojo, lista y «Questo prezzo resta su questa schermata per 09:38»).

La diferencia está en el sorteo: el descuento lo reparte la plataforma (test A/B de la oferta: cada compra cae al azar
en la A o en la B, cada una con su descuento) y la página lo lee del token ``{discount}``; los rodillos solo lo
destapan. Lo que se cobra sale de la oferta, y los precios se pintan con los tokens ``{compare}``, ``{price}`` y
``{savings}``. La página dice los premios posibles. Si el token no trae un premio conocido, no gira: enseña el precio
real y los botones.

El archivo es ``upsells/<clave>-recuperacion.md`` con frontmatter ``plantilla: tragamonedas`` (los textos, en el
idioma del país) y sin cuerpo.
"""
from __future__ import annotations

import re
from html import escape

import yaml

_FRONT = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)
_NEGRITA = re.compile(r"\*\*(.+?)\*\*")
_TEXTOS = ("etiqueta", "saludo", "titular", "posibles", "producto", "ahorro", "rechazar")
_MAQUINA = ("rotulo", "titulo", "subtitulo", "premio", "boton", "girando", "pie")
_RESULTADO = ("sufijo", "texto")
_ACEPTAR = ("titulo", "subtitulo")
_CONTADOR = ("texto", "vencido")


def datos_de(texto: str) -> dict | None:
    """Los datos de una página ``plantilla: tragamonedas``; None si el archivo no es de esta plantilla."""
    m = _FRONT.match(texto or "")
    if not m:
        return None
    try:
        datos = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None
    return datos if isinstance(datos, dict) and datos.get("plantilla") == "tragamonedas" else None


def _texto_ok(valor: object) -> bool:
    return isinstance(valor, str) and bool(valor.strip())


def validar(datos: dict) -> list[str]:
    """Problemas de los datos de la página; ``[]`` = bien."""
    problemas: list[str] = []
    premios = datos.get("premios")
    if (not isinstance(premios, list) or len(premios) < 2 or len(set(map(str, premios))) != len(premios)
            or not all(isinstance(p, int) and not isinstance(p, bool) and 5 <= p <= 95 for p in premios)):
        problemas.append("premios: al menos dos descuentos distintos, enteros de 5 a 95")
        premios = []
    problemas += [f"falta el texto «{c}»" for c in _TEXTOS if not _texto_ok(datos.get(c))]
    for bloque, campos in (("maquina", _MAQUINA), ("resultado", _RESULTADO), ("aceptar", _ACEPTAR),
                           ("contador", _CONTADOR)):
        sub = datos.get(bloque)
        sub = sub if isinstance(sub, dict) else {}
        problemas += [f"falta el texto «{bloque}.{c}»" for c in campos if not _texto_ok(sub.get(c))]
    parrafos = datos.get("parrafos")
    if not isinstance(parrafos, list) or not parrafos or not all(_texto_ok(p) for p in parrafos):
        problemas.append("parrafos: una lista de textos")
    lista = datos.get("lista")
    if not isinstance(lista, list) or not lista or not all(_texto_ok(x) for x in lista):
        problemas.append("lista: una lista de textos")
    minutos = (datos.get("contador") or {}).get("minutos") if isinstance(datos.get("contador"), dict) else None
    if not isinstance(minutos, int) or isinstance(minutos, bool) or not 1 <= minutos <= 60:
        problemas.append("contador.minutos: de 1 a 60")
    posibles = datos.get("posibles") if _texto_ok(datos.get("posibles")) else ""
    if premios and not all(re.search(rf"(?<!\d){p}\s*%", posibles) for p in premios):
        problemas.append("posibles: tiene que decir cada premio posible («40 %», «60 %»)")
    return problemas


def _t(texto: str) -> str:
    """Texto escapado, con ``**negrita**``."""
    return _NEGRITA.sub(r"<strong>\1</strong>", escape(str(texto).strip()))


_CSS = """
html,body{margin:0!important;background:#fbf6ee!important}
.ts{box-sizing:border-box;max-width:560px;margin:0 auto;padding:0 18px 48px;background:#fbf6ee;color:#3b3b3b;
font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;font-size:17px;line-height:1.55;text-align:center;
-webkit-text-size-adjust:100%}
.ts *{box-sizing:border-box}
.ts [hidden]{display:none!important}
.ts-raya{height:14px;margin:0 -18px 22px;background:repeating-linear-gradient(135deg,#c0283d 0 14px,#fff 14px 28px)}
.ts-mono{font-family:ui-monospace,"SFMono-Regular",Menlo,Consolas,"Courier New",monospace;letter-spacing:.22em;
text-transform:uppercase}
.ts-etq{display:inline-block;padding:6px 16px;border:2px solid #c0283d;color:#c0283d;font-size:14px;font-weight:700;
margin-bottom:14px}
.ts-h{font-family:"Arial Black","Helvetica Neue",Arial,sans-serif;font-weight:900;line-height:1.08;margin:0 0 16px}
.ts-h1{color:#1f3b2d;font-size:34px;display:block}
.ts-h2{color:#c0283d;font-size:30px;display:block}
.ts p{margin:0 0 14px}
.ts strong{color:#1e1e1e}
.ts-rot{color:#c0283d;font-size:14px;font-weight:700;margin:22px 0 14px}
.ts-maq{position:relative;margin:30px 34px 10px 6px;padding:0 16px 16px;border-radius:22px;
background:linear-gradient(180deg,#b8233a,#7d1626);border:4px solid #e8b04a;
box-shadow:0 0 0 2px #6e1220,0 14px 34px rgba(120,20,30,.35)}
.ts-cab{position:relative;top:-22px;margin:0 auto -8px;max-width:84%;padding:9px 10px 8px;border-radius:12px;
background:#2a0e12;border:3px solid #e8b04a;color:#f6c75a}
.ts-cab b{display:block;font-family:"Arial Black",Arial,sans-serif;font-size:clamp(15px,5.2vw,21px);
letter-spacing:.04em;white-space:nowrap}
.ts-cab small{display:block;font-size:11px;color:#f3e3c0;margin-top:2px}
.ts-luces{display:flex;justify-content:space-between;padding:0 4px;margin:6px 0 10px}
.ts-luces i{width:11px;height:11px;border-radius:50%;background:#fbe7a6;box-shadow:0 0 8px #ffd76a}
.ts-luces i:nth-child(even){background:#7a3b1d;box-shadow:none}
.ts-gira .ts-luces i{animation:ts-luz .5s infinite alternate}
.ts-gira .ts-luces i:nth-child(even){animation-delay:.25s}
@keyframes ts-luz{from{background:#fbe7a6;box-shadow:0 0 8px #ffd76a}to{background:#7a3b1d;box-shadow:none}}
.ts-pre{display:flex;justify-content:space-between;align-items:center;padding:8px 12px;border-radius:8px;
background:#2a0e12;border:2px solid #9b3a2a;color:#f3e3c0;font-size:13px;text-align:left}
.ts-pre i{width:12px;height:12px;border-radius:50%;background:#e2342f;box-shadow:0 0 8px #ff4d4d}
.ts-ven{position:relative;display:flex;gap:10px;margin:12px 0;padding:12px;border-radius:12px;background:#0d0a0a;
border:3px solid #e8b04a}
.ts-ven:after{content:"";position:absolute;z-index:2;left:2px;right:2px;top:50%;height:2px;background:#e2342f;
box-shadow:0 0 6px #e2342f}
.ts-ven:before{content:"";position:absolute;z-index:2;left:-2px;right:-2px;top:calc(50% - 6px);height:14px;
background:linear-gradient(90deg,#e2342f 0 8px,transparent 8px calc(100% - 8px),#e2342f calc(100% - 8px));
clip-path:polygon(0 0,8px 50%,0 100%,100% 0,calc(100% - 8px) 50%,100% 100%)}
.ts-rod{flex:1;height:96px;line-height:96px;border-radius:8px;overflow:hidden;
background:linear-gradient(180deg,#9a9a9a,#fff 22%,#fff 78%,#9a9a9a);color:#151515;
font-family:"Arial Black",Arial,sans-serif;font-size:52px;font-weight:900}
.ts-rod.ts-mueve{animation:ts-baja .09s linear infinite}
@keyframes ts-baja{from{transform:translateY(-18px)}to{transform:translateY(18px)}}
.ts-palanca{position:absolute;right:-30px;top:38%;width:26px;height:110px}
.ts-palanca:before{content:"";position:absolute;left:0;bottom:0;width:14px;height:44px;border-radius:3px;
background:linear-gradient(90deg,#b8862c,#f2c96a,#b8862c)}
.ts-palo{position:absolute;left:9px;bottom:30px;width:9px;height:70px;border-radius:5px;transform-origin:50% 100%;
background:linear-gradient(90deg,#9a9a9a,#f2f2f2,#9a9a9a);transition:transform .35s}
.ts-palo:before{content:"";position:absolute;left:-9px;top:-22px;width:27px;height:27px;border-radius:50%;
background:radial-gradient(circle at 35% 35%,#ff8a8a,#d1202c 60%,#8d0f18)}
.ts-gira .ts-palo{transform:scaleY(-.55)}
.ts-tirar{display:block;width:100%;margin-top:4px;padding:15px 10px;border:2px solid #f8d987;border-radius:12px;
background:linear-gradient(180deg,#f6c457,#d9902a);color:#3a1208;cursor:pointer;
font-family:"Arial Black",Arial,sans-serif;font-size:19px;font-weight:900;letter-spacing:.06em;line-height:1.2;
box-shadow:0 4px 0 #8c4b14}
.ts-tirar:disabled{cursor:default}
.ts-ranura{height:22px;margin:12px auto 10px;width:62%;border-radius:0 0 10px 10px;background:#160708;
border:2px solid #e8b04a;border-top:0}
.ts-pie{color:#f9e7c7;font-size:15px;margin:0}
.ts-pos{font-size:13px;color:#6b6b6b;margin:8px 0 0}
.ts-no{display:inline-block;margin:18px 0 0;padding:6px;background:none;border:0;color:#555;font:inherit;
font-size:16px;text-decoration:underline;cursor:pointer}
.ts-res{margin-top:22px}
.ts-off{display:inline-block;padding:2px 22px;border:3px solid #c0283d;font-family:"Arial Black",Arial,sans-serif;
font-weight:900;font-size:58px;line-height:1.15;color:#1f3b2d}
.ts-img{display:block;max-width:86%;margin:18px auto 8px}
.ts-prod{font-family:"Arial Black",Arial,sans-serif;font-weight:900;font-size:24px;color:#1e1e1e;margin:10px 0 4px}
.ts-precio{display:flex;justify-content:center;align-items:baseline;gap:12px;flex-wrap:wrap}
.ts-precio s{color:#7a7a7a;font-size:22px}
.ts-precio b{font-family:"Arial Black",Arial,sans-serif;color:#c0283d;font-size:46px;line-height:1.1}
.ts-ahorro{display:inline-block;margin:8px 0 16px;padding:5px 16px;border-radius:999px;background:#e3eee6;
color:#1f5a35;font-weight:700}
.ts-si{display:block;width:100%;padding:14px 12px;border:0;border-radius:12px;background:#c0283d;color:#fff;
cursor:pointer;box-shadow:0 5px 0 #7d1626;font:inherit;line-height:1.3}
.ts-si b{display:block;font-size:21px}
.ts-si small{display:block;font-size:15px;opacity:.95}
.ts-lista{list-style:none;padding:0;margin:18px 0 10px}
.ts-lista li{margin:0 0 6px;color:#555}
.ts-lista li:before{content:"\\2713 ";color:#c0283d;font-weight:900}
.ts-reloj{font-size:14px;color:#8d1d2c;font-weight:700}
.ts-vencido{margin-top:12px;padding:12px;border-radius:12px;background:#eee;font-weight:700}
"""

# Los rodillos destapan el descuento que la plataforma sorteó para esta compra ({discount}); no eligen nada.
_JS = r"""<script>(function(){var s=document.querySelector('[data-ts]');if(!s)return;
var ops=s.getAttribute('data-ts').split(','),m=(s.querySelector('[data-ts-sorteo]').textContent||'')
.replace(',','.').match(/\d+(\.\d+)?/),n=m?String(Math.round(+m[0])):'',ok=ops.indexOf(n)>=0,
id=s.getAttribute('data-ts-id'),k='ts:'+location.pathname+':'+id,kr='tsr:'+location.pathname+':'+id,
rod=[].slice.call(s.querySelectorAll('.ts-rod')),b=s.querySelector('.ts-tirar'),
q=function(x){return document.querySelector(x)},res=q('[data-ts-res]');
var im=q('.ts-img');if(im){var ch=function(){if(!im.naturalWidth)im.remove()};
if(im.complete)ch();else{im.addEventListener('error',ch);im.addEventListener('load',ch)}}
var nom=q('[data-ts-nombre]');if(nom){var v=(nom.getAttribute('data-ts-nombre')||'').trim();
if(!v||v.indexOf('{')>=0)nom.remove()}
function reloj(){var r=q('[data-ts-reloj]');if(!r)return;var f=0;try{f=+localStorage.getItem(kr)}catch(e){}
if(!f){f=Date.now()+1000*r.getAttribute('data-ts-reloj');try{localStorage.setItem(kr,f)}catch(e){}}
var o=r.querySelector('b'),i;function t(){var x=Math.max(0,Math.ceil((f-Date.now())/1000));
o.textContent=('0'+Math.floor(x/60)).slice(-2)+':'+('0'+x%60).slice(-2);if(x<=0){clearInterval(i);
document.querySelectorAll('[data-pp-accept]').forEach(function(e){e.remove()});var w=q('[data-ts-vencido]');
if(w)w.hidden=false}}i=setInterval(t,1000);t()}
function mostrar(fin){res.hidden=false;b.hidden=true;var p=q('[data-ts-pnum]');if(p)p.textContent=fin?n:'';
document.querySelectorAll('[data-ts-n]').forEach(function(e){e.textContent=n});
if(!fin)document.querySelectorAll('[data-ts-solo-premio]').forEach(function(e){e.hidden=true});reloj()}
if(!ok){s.hidden=true;q('[data-ts-pos]').hidden=true;mostrar(false);return}
var d=[n.charAt(0),n.charAt(1)||'','%'];
function quieto(){rod.forEach(function(r,j){r.textContent=d[j];r.classList.remove('ts-mueve')})}
var h=0;try{h=localStorage.getItem(k)==='1'}catch(e){}if(h){quieto();mostrar(true);return}
function tirar(){if(b.disabled)return;b.disabled=true;b.textContent=b.getAttribute('data-ts-girando');
s.classList.add('ts-gira');var i=setInterval(function(){rod.forEach(function(r){if(r.classList.contains('ts-mueve'))
r.textContent=Math.floor(Math.random()*10)})},70);rod.forEach(function(r,j){r.classList.add('ts-mueve');
setTimeout(function(){r.classList.remove('ts-mueve');r.textContent=d[j];if(j==2){clearInterval(i);
s.classList.remove('ts-gira');try{localStorage.setItem(k,'1')}catch(e){}setTimeout(function(){mostrar(true);
res.scrollIntoView({behavior:'smooth',block:'start'})},700)}},1500+j*600)})}
b.addEventListener('click',tirar);s.querySelector('.ts-palanca').addEventListener('click',tirar)})();</script>"""


def html(datos: dict, pagina_id: str) -> str:
    """El HTML de la página (sin ``<html>`` ni ``<body>``, como lo pide el conector)."""
    maq, res, si, cont = datos["maquina"], datos["resultado"], datos["aceptar"], datos["contador"]
    premios = ",".join(str(p) for p in datos["premios"])
    luces = "<i></i>" * 11
    saludo = _t(datos["saludo"])
    # «Чакай, Иван.»: el nombre sale del token {first-name}; sin nombre queda «Чакай.».
    saludo = saludo.replace("{nombre}", '<span data-ts-nombre="{first-name}">, {first-name}</span>')
    parrafos = "\n".join(f"<p>{_t(p)}</p>" for p in datos["parrafos"])
    lista = "".join(f"<li>{_t(x)}</li>" for x in datos["lista"])
    return f"""<style>{_CSS}</style>
<div class="ts">
<div class="ts-raya"></div>
<div class="ts-etq ts-mono">{_t(datos["etiqueta"])}</div>
<h1 class="ts-h"><span class="ts-h1">{saludo}</span><span class="ts-h2">{_t(datos["titular"])}</span></h1>
{parrafos}
<p class="ts-rot ts-mono">&#9646; {_t(maq["rotulo"])} &#9646;</p>
<div class="ts-maq" data-ts="{premios}" data-ts-id="{pagina_id}">
<span data-ts-sorteo hidden>{{discount}}</span>
<div class="ts-cab"><b>&#9733; {_t(maq["titulo"])} &#9733;</b><small class="ts-mono">{_t(maq["subtitulo"])}</small></div>
<div class="ts-luces">{luces}</div>
<div class="ts-pre ts-mono"><span>{_t(maq["premio"])} <span data-ts-pnum>??</span></span><i></i></div>
<div class="ts-ven"><div class="ts-rod">?</div><div class="ts-rod">?</div><div class="ts-rod">?</div></div>
<div class="ts-palanca" aria-hidden="true"><div class="ts-palo"></div></div>
<button type="button" class="ts-tirar" data-ts-girando="{escape(maq["girando"])}">{_t(maq["boton"])}</button>
<div class="ts-ranura"></div>
<div class="ts-luces">{luces}</div>
<p class="ts-pie">{_t(maq["pie"])}</p>
</div>
<p class="ts-pos" data-ts-pos>{_t(datos["posibles"])}</p>
<div class="ts-res" data-ts-res hidden>
<div data-ts-solo-premio><div class="ts-off"><span data-ts-n></span>% {_t(res["sufijo"])}</div>
<p>{_t(res["texto"])}</p></div>
<img class="ts-img" src="{{product-image}}" alt="{escape(datos["producto"])}">
<p class="ts-prod">{_t(datos["producto"])}</p>
<div class="ts-precio"><s>{{compare}}</s><b>{{price}}</b></div>
<div class="ts-ahorro">{_t(datos["ahorro"])} {{savings}}</div>
<button type="button" class="ts-si" data-pp-accept><b>{_t(si["titulo"])}</b><small data-ts-solo-premio>\
{_t(si["subtitulo"]).replace("{n}", "<span data-ts-n></span>")}</small></button>
<ul class="ts-lista">{lista}</ul>
<p class="ts-reloj ts-mono" data-ts-reloj="{int(cont["minutos"]) * 60}">&#9203; {_t(cont["texto"])} \
<b>{int(cont["minutos"]):02d}:00</b></p>
<p class="ts-vencido" data-ts-vencido hidden>{_t(cont["vencido"])}</p>
</div>
<button type="button" class="ts-no" data-pp-decline>{_t(datos["rechazar"])}</button>
</div>
{_JS}
"""
