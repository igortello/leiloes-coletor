"""Coletor Frazão Leilões (frazaoleiloes.com.br) — imóveis de bancos (Inter, Santander; Itaú só contado).

Usa a mesma busca pública que o site usa para montar a vitrine (/Sale/SearchLotResult, HTML),
numa chamada só, a partir de uma página aberta do site. Os cartões trazem vendedor (logo),
título com cidade/UF, endereço, área, praças e valores. Só os candidatos (banco pedido, cidade,
faixa de valor, tipo) têm a página do lote aberta, com pausa entre elas, para ler a forma de
pagamento, ocupação, matrícula e débitos.
"""
import html as _html, json, re, time
from collections import Counter
from datetime import datetime

from sold import norm, num_br, texto_html, classifica_pagamento, FRACAO

BASE = "https://www.frazaoleiloes.com.br"
BUSCA = ("/Sale/SearchLotResult?uf=&cidade=&bairro=&tipoimovel=&subtipoImovel=&area=&preco=&term=&start=0&limit=3000"
         "&page=1&vendedor=&categoria=&subcategoria=&tipolote=&documentacaolote=&loteAtivo=true&ExibirInternosPrimeiro=true"
         "&end=&cep=&segmento=&modalidadeId=&litoral=false&__RequestVerificationToken={tok}")
PAUSA = 2.0
MAX_DETALHES = 80
PREFIXO = {"Santander": "FS", "Inter": "FI", "Itaú": "FT"}
INTER = re.compile(r"\bINTER\b|INTERMEDIUM|INTER ?& ?CO")


def banco_de(vendedor):
    v = norm(_html.unescape(vendedor or ""))
    if "SANTANDER" in v:
        return "Santander"
    if INTER.search(v):
        return "Inter"
    if "ITAU" in v:
        return "Itaú"
    return None


def _data(s):
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})(?:\s*às\s*(\d{1,2}h\d{2}))?", s or "")
    return (f"{m.group(3)}-{m.group(2)}-{m.group(1)}", m.group(4)) if m else (None, None)


def cidade_uf_titulo(t):
    t = _html.unescape(t or "").strip().rstrip(".")
    m = re.search(r"[,\s]+([A-Z]{2})$", t)
    if not m:
        return None, None
    resto = t[:m.start()].rstrip(", ")
    cid = resto.split(",")[-1] if "," in resto else re.split(r"\s(?:em|no|na|de|do|da)\s", resto)[-1]
    return cid.strip(), m.group(1)


def ler_cartoes(txt):
    out, vistos = [], set()
    for c in txt.split('id="card-lote"')[1:]:
        lid = re.search(r'data-lote-id="(\d+)"', c)
        if not lid or lid.group(1) in vistos:
            continue
        vistos.add(lid.group(1))
        g = lambda pat: (re.search(pat, c, re.S) or [None, None])[1]
        titulo = _html.unescape(g(r'<b title="([^"]*)"') or "")
        pr = []
        for bloco in re.findall(r"((?:\d)º Leilão:|Leilão:)\s*([^<]*)<br\s*/?>\s*<span class=\"price-line\">\s*R\$\s*([\d.,]+)", c):
            d, h = _data(bloco[1])
            pr.append({"data": d, "hora": h, "valor": num_br(bloco[2])})
        area = g(r"<span>([\d.,]+)\s*m²</span>")
        cid, uf = cidade_uf_titulo(titulo)
        out.append({"id": lid.group(1), "href": g(r'href="(/lote/[^"]+)"'), "tipo": g(r'data-tipo="([^"]*)"'),
                    "endereco_curto": _html.unescape(g(r'data-addr="([^"]*)"') or ""), "titulo": titulo,
                    "vendedor": _html.unescape(g(r'alt="Logo ([^"]*)"') or ""), "area": num_br(area), "pracas": pr,
                    "cidade": cid, "uf": uf, "lote": (g(r"Lote nº\s*([^&<]+)") or "").strip(),
                    "status": _html.unescape(g(r'class="label-md[^"]*">([^<]+)<') or "").strip()})
    return out


def achar(pat, t, flags=re.I):
    m = re.search(pat, t or "", flags)
    return m.group(1).strip() if m else None


def debitos(t):
    linhas = [l.strip() for l in (t or "").split("\n")]
    for i, l in enumerate(linhas):
        if re.search(r"IPTU|condom", l, re.I) and (re.search(r"d[ée]bit|quitad", l, re.I) or (i + 1 < len(linhas) and re.search(r"d[ée]bit|quitad", linhas[i + 1], re.I))):
            txt = l if re.search(r"d[ée]bit|quitad", l, re.I) and len(l) > 25 else (l + " " + (linhas[i + 1] if i + 1 < len(linhas) else ""))
            return re.sub(r"\s+", " ", txt)[:260]
    m = re.search(r"([^\n]*n[ãa]o possui d[ée]bitos[^\n]*)", t or "", re.I)
    return m.group(1).strip()[:200] if m else None


def ler_detalhe(htm):
    """Campos da página do lote."""
    info = achar(r'Informações sobre o Lote(.*?)(?:Liberado para Lance|Aguarde Libera|Envio de Proposta|Maior lance atual|<div class="col-lg-4)', htm, re.I | re.S) or ""
    t = texto_html(info)
    tudo = texto_html(htm)
    cond = achar(r"Condi[çc][õo]es de pagamento:?\s*\n?(.*?)(?:\n\s*(?:Lance (?:m[íi]nimo|inicial)|C[óo]digo do Im[óo]vel|Valor de avalia)|$)", t, re.I | re.S)
    cond = re.sub(r"\s*\n\s*", " ", cond or "").strip(" -;") or None
    lic = re.search(r'href="/leilao/(\d+)/([^"]+)"\s*>\s*([^<]+?)\s*</a>', htm)
    ocup = "Ocupado" if re.search(r"Im[óo]vel Ocupado", tudo) else "Desocupado" if re.search(r"Im[óo]vel Desocupado", tudo) else None
    m_end = re.search(r'"name":"Endereço","value":"([^"]+?)(?:\s+Im[óo]vel (?:Des)?[Oo]cupado|\s+\d+ Visitas|")', htm)
    endereco = _html.unescape(m_end.group(1)).strip() if m_end else None
    return {
        "texto": t, "condicoes": cond,
        "avaliacao": num_br(achar(r"(?:Valor de )?[Aa]valia[çc][ãa]o(?: do im[óo]vel)?:?\s*R\$\s*([\d.,]+)", t)),
        "matricula": achar(r"Matr[íi]cula(?:\(s\))?(?: n[ºo°.]*)?:?\s*([\d.\-/]+)", t),
        "oficio": achar(r"Matr[íi]cula[^\n]*?\d\s+d[oa]\s+([^\n–]+?)\s*(?:–|-\s*CNM|$)", t, re.I | re.M),
        "debitos": debitos(t),
        "ocupacao": ocup, "condicionado": bool(re.search(r"condicionad[oa] [àa] aprova[çc][ãa]o do vendedor", t + tudo, re.I)),
        "codigo": achar(r"C[óo]digo do Im[óo]vel:?\s*([\w.\-]+)", t),
        "licitacao_id": lic.group(1) if lic else None, "licitacao": _html.unescape(lic.group(3)) if lic else None,
        "endereco": endereco,
        "area": num_br(achar(r"[ÁA]rea (?:privativa|[úu]til)[^:\n]*:\s*([\d.,]+)", t)),
        "quartos": achar(r"(\d+)\s*(?:dormit[óo]rios?|quartos?)", t),
        "vaga": achar(r"(\d+|uma|01|02)\s*vagas?", t) or (re.search(r"\bvaga", t, re.I) and "1"),
    }


def montar(c, det, banco):
    pr = c["pracas"]
    p1 = pr[0] if pr else {}
    p2 = pr[1] if len(pr) > 1 else {}
    cond = det.get("condicoes")
    fin, fin_tipo = classifica_pagamento(cond, banco)
    endereco = det.get("endereco") or c["endereco_curto"]
    m = re.search(r",\s*([^,]+?),\s*([A-Z]{2})\s*$", endereco or "")
    cidade, uf = (m.group(1).strip(), m.group(2)) if m else (c["cidade"], c["uf"])
    bairro = None
    if m:
        partes = [x.strip() for x in endereco[:m.start()].split(",")]
        bairro = partes[-1] if len(partes) >= 3 else None
    tipo = c["tipo"] or None
    vaga = det.get("vaga")
    d = {
        "banco": banco, "fonte": "Frazão", "numero_bem": f"{PREFIXO[banco]}{c['id']}", "id_oferta": int(c["id"]),
        "uf": uf, "cidade": cidade, "bairro": bairro, "endereco": endereco, "empreendimento": None, "tipo": tipo,
        "area_privativa": det.get("area") or c["area"], "area_total": None,
        "quartos": int(det["quartos"]) if str(det.get("quartos") or "").isdigit() else None,
        "vaga": ("sim" if vaga and str(vaga) not in ("0",) else None) if vaga else ("sim" if re.search(r"vaga", c["titulo"], re.I) else None),
        "lance_minimo": p1.get("valor"), "avaliacao": det.get("avaliacao"), "valor_alvo": None,
        "desconto_pct": round(1 - (p2.get("valor") or p1.get("valor")) / det["avaliacao"], 4) if det.get("avaliacao") and p1.get("valor") else None,
        "modalidade": f"Leilão {'em 2 praças ' if p2 else ''}(Frazão)", "descricao": c["titulo"],
        "financiamento": fin, "financiamento_tipo": fin_tipo, "financiamento_texto": cond, "financiamento_lista": None,
        "fgts": "FGTS" in norm(cond),
        "data_leilao": p1.get("data"), "hora_leilao": p1.get("hora"),
        "lance_2_leilao": p2.get("valor"), "data_2_leilao": p2.get("data"), "hora_2_leilao": p2.get("hora"),
        "licitacao": f"{det.get('licitacao')}" if det.get("licitacao") else None, "lote": c["lote"] or None,
        "leiloeiro": "Frazão Leilões", "matricula": det.get("matricula"), "oficio": det.get("oficio"),
        "regra_condominio": det.get("debitos"), "regra_tributos": det.get("debitos"), "averbacao_leiloes": None,
        "ocupacao": det.get("ocupacao"), "comissao_pct": None, "codigo_imovel": det.get("codigo"),
        "anexos": [], "link": BASE + c["href"],
    }
    if p2.get("valor"):
        d["lance_1_leilao"] = p1.get("valor")
    al = []
    if d["ocupacao"] is None: al.append("Ocupação não informada")
    elif d["ocupacao"] == "Ocupado": al.append("Ocupado")
    if d["vaga"] is None: al.append("Vaga não informada")
    if det.get("condicionado"): al.append("Lance condicionado à aprovação do vendedor")
    if fin_tipo == "direto do banco":
        ent = achar(r"(?:entrada|sinal)(?: m[íi]nim[ao])?(?: de)?\s*(\d{1,2})\s*%", cond)
        juros = achar(r"juros de\s*(\d{1,2}(?:[.,]\s?\d{1,2})?)\s*%", cond)
        if ent: d["entrada_min_pct"] = int(ent) / 100
        if juros:
            d["juros_aa"] = round(float(re.sub(r"\s", "", juros).replace(",", ".")) / 100, 4)
            d["juros_indice"] = "IPCA" if "IPCA" in norm(cond) else None
        al.append(f"Financiamento direto do {banco}" + (f": entrada mínima {ent}%" if ent else "") + " — confirmar no edital")
    al.append("Comissão do leiloeiro: confirmar no edital")
    if p2.get("valor"): al.append("2º leilão em " + datetime.strptime(p2["data"], "%Y-%m-%d").strftime("%d/%m") + ": R$ " + f"{p2['valor']:,.0f}".replace(",", "."))
    d["alertas"] = al
    return d


def buscar_txt(pg, url):
    r = pg.evaluate("async (u) => { const r = await fetch(u, {headers: {'X-Requested-With': 'XMLHttpRequest'}});"
                    " return {status: r.status, txt: await r.text()}; }", url)
    if r["status"] != 200:
        raise RuntimeError(f"Frazão respondeu {r['status']}")
    return r["txt"]


def coletar(crit, hoje, cidades, diag, bancos=("Inter", "Santander")):
    from playwright.sync_api import sync_playwright
    lmin, lmax = crit.get("lance_min", 0), crit.get("lance_max", 10**12)
    so_apto = crit.get("somente_apartamentos", True)
    conts = {b: {"lotes_frazao": 0, "lotes_banco": 0, "candidatos": 0, "sem_financiamento": 0, "fora_cidade": 0,
                 "fora_faixa": 0, "fora_tipo": 0, "detalhe_falhou": 0} for b in bancos}
    condicoes = {b: Counter() for b in bancos}
    vendedores, cond_itau = Counter(), Counter()
    imoveis = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(locale="pt-BR", timezone_id="America/Sao_Paulo",
                            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36")
        ctx.route("**/*", lambda r: r.abort() if r.request.resource_type in ("image", "media", "font") else r.continue_())
        pg = ctx.new_page()
        pg.goto(BASE + "/leiloes", wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(4000)
        tok = pg.evaluate("() => (document.querySelector('input[name=__RequestVerificationToken]')||{}).value || ''")
        cartoes = ler_cartoes(buscar_txt(pg, BASE + BUSCA.format(tok=tok)))
        diag["frazao_lotes"] = len(cartoes)
        cand = []
        for c in cartoes:
            vendedores[c["vendedor"]] += 1
            banco = banco_de(c["vendedor"])
            if banco not in conts:
                continue
            ct = conts[banco]
            ct["lotes_banco"] += 1
            if norm(c["cidade"]) not in cidades.get(c["uf"] or "", set()):
                ct["fora_cidade"] += 1; continue
            if not any(lmin <= (x["valor"] or 0) <= lmax for x in c["pracas"]):
                ct["fora_faixa"] += 1; continue
            if so_apto and norm(c["tipo"]) != "APARTAMENTO":
                ct["fora_tipo"] += 1; continue
            if FRACAO.search(norm(c["titulo"])) or re.match(r"(?i)direitos", c["titulo"]):
                ct["fora_tipo"] += 1; continue
            cand.append((c, banco))
        for c, banco in cand[:MAX_DETALHES]:
            ct = conts[banco]
            try:
                time.sleep(PAUSA)
                pg.goto(BASE + c["href"], wait_until="domcontentloaded", timeout=60000)
                pg.wait_for_timeout(1500)
                det = ler_detalhe(pg.content())
            except Exception as e:  # noqa
                ct["detalhe_falhou"] += 1
                det = {}
                diag.setdefault("frazao_falhas", []).append({"lote": c["id"], "erro": str(e)[:200]})
            d = montar(c, det, banco)
            if not det:
                d["alertas"].insert(0, "Anúncio não lido")
            if norm(d["cidade"]) not in cidades.get(d["uf"] or "", set()):
                ct["fora_cidade"] += 1; continue
            condicoes[banco][(d.get("financiamento_texto") or "(sem condição)")[:300]] += 1
            ct["candidatos"] += 1
            if d["financiamento"] is False:
                ct["sem_financiamento"] += 1
            imoveis.append(d)
        b.close()
    for bco, ct in conts.items():
        ct["lotes_frazao"] = len(cartoes)
        ct["condicoes"] = dict(condicoes[bco].most_common(8))
    diag["frazao_vendedores"] = dict(vendedores.most_common(15))
    return imoveis, conts
