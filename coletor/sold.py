"""Coletor SOLD — imóveis do Santander e do Banco Inter vendidos pela SOLD (grupo Superbid).

Usa a mesma API pública que o site www.sold.com.br usa para montar as listas
(offer-query.superbid.net), chamada a partir de uma página aberta da SOLD, com
poucas requisições e pausa entre elas. Não abre superbid.net (que pede verificação
anti-robô) nem santanderimoveis.com.br (que bloqueia servidores).

Só entram ofertas cujo vendedor é um dos bancos pedidos (Santander, Inter). A forma
de pagamento vem do campo "Condições de Pagamento" de cada lote (ex.: "À vista ou
Financiamento em até 420 meses."). Nos leilões de alienação fiduciária o Santander tem
vendido só à vista. O Inter tem oferecido "financiamento direto" do próprio banco
(entrada mínima de 30% a 50%, 24 a 240 meses, juros + IPCA).
"""
from collections import Counter
import html as _html, json, re, time, unicodedata
from datetime import datetime, timedelta, timezone

SOLD = "https://www.sold.com.br/"
API = ("https://offer-query.superbid.net/offers/?portalId=[2,15]&requestOrigin=store&locale=pt_BR&timeZoneId=UTC"
       "&searchType=opened&filter=stores.id:[1161];product.productType.description:imoveis;isShopping:false"
       "&pageSize={tam}&pageNumber={pag}&orderBy=price:asc")
TAM = 50
PAUSA = 1.5
BRT = timezone(timedelta(hours=-3))
FRACAO = re.compile(r"FRACAO|PARTE IDEAL|DIREITOS? SOBRE|USUFRUTO|NUA[- ]PROPRIEDADE|\d+(?:[.,]\d+)?\s*%\s*(?:DO|DA|DE)\s+IMOVEL", re.I)


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().upper()


def num_br(s):
    s = str(s or "").strip().replace("R$", "").replace(" ", "")
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def texto_html(h):
    h = re.sub(r"(?i)<br\s*/?>|</(p|div|li|b|strong)>", "\n", h or "")
    h = _html.unescape(re.sub(r"<[^>]+>", " ", h))
    return "\n".join(l for l in (re.sub(r"[ \t\xa0]+", " ", x).strip() for x in h.splitlines()) if l)


def slug(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s)).strip("-")


INTER = re.compile(r"\bBANCO INTER\b|\bINTER S ?/? ?A\b|\bINTERMEDIUM\b|^INTER\b")
PREFIXO = {"Santander": "S", "Inter": "I"}


def banco_de(o):
    """'Santander', 'Inter' ou None, pelo vendedor ou pelo nome do evento."""
    vend = norm((o.get("seller") or {}).get("name"))
    ev = norm((o.get("auction") or {}).get("desc"))
    if "SANTANDER" in vend or ev.startswith("SANTANDER"):
        return "Santander"
    if INTER.search(vend) or INTER.search(ev):
        return "Inter"
    return None


def classifica_pagamento(cond, banco):
    """(financiamento True/False/None, tipo). Tipos: "bancário" (financiamento do banco em até N meses,
    como o Santander), "direto do banco" (Inter: sinal/entrada + 24 a 240 parcelas com o próprio banco).
    Parcelamento curto (até 60 parcelas, ex.: sinal de 40% + 18x) não é financiamento."""
    c = norm(cond)
    if not c:
        return None, None
    # regras de outros tipos de imóvel (ex.: "Terrenos pagamento somente à vista") não valem para apartamentos
    c = "; ".join(x for x in re.split(r";|\n", c) if not re.search(r"\b(TERRENOS?|LOTES DE TERRENO|IMOVEIS RURAIS|GALPOES)\b", x)) or c
    if re.search(r"SEM FINANCIAMENTO|NAO (?:ACEITA|PERMITE|HA) FINANCIAMENTO|SOMENTE A VISTA|APENAS A VISTA", c):
        return False, None
    meses = [int(x) for x in re.findall(r"(\d{2,3})\s*(?:X\b|PARCELAS|MESES|PRESTA)", c)]
    meses += [int(x) for x in re.findall(r"(?:EM ATE|ATE|LIMITADA A|A)\s*(\d{2,3})\s*(?:\(|X|PARCELAS|MESES|SUCESSIVAS)", c)]
    longo = max(meses) if meses else None
    if re.search(r"FINANCIAMENTO|FINANCIADO", c):
        if banco == "Inter" or re.search(r"SINAL|ENTRADA DE \d", c) and not re.search(r"FINANCIAMENTO (?:BANCARIO|EM ATE|DE ATE)", c):
            return True, "direto do banco"
        return True, "bancário"
    if re.search(r"PARCELA|SALDO EM ATE|\d+\s*X\b", c):
        if longo and longo >= 120:
            return True, ("bancário" if banco == "Santander" else "direto do banco")
        return False, None
    return (False, None) if "VISTA" in c else (None, None)


def campos_template(p):
    out = {}
    for g in ((p.get("template") or {}).get("groups") or []):
        for pr in g.get("properties") or []:
            v = pr.get("value")
            if v not in (None, ""):
                out[pr.get("id")] = v
    return out


def achar(pat, t):
    m = re.search(pat, t, re.I)
    return m.group(1).strip() if m else None


def limpa_cidade(c):
    c = re.sub(r"(?i)^\s*(?:em|no|na|do|da|munic[íi]pio de)\s+", "", c or "").strip()
    return re.sub(r"(?i)^(?:em|no|na)\s+", "", c)


MESES = {"jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6, "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12}


def data_pt(t):
    """'18/nov/2026' ou '18 de novembro de 2026' ou '18/11/2026' -> date."""
    m = re.search(r"(\d{1,2})\s*(?:/|de)\s*([a-zç]{3})[a-zç]*\.?\s*(?:/|de)\s*(\d{4})", t or "", re.I)
    if m and m.group(2).lower()[:3] in MESES:
        return datetime(int(m.group(3)), MESES[m.group(2).lower()[:3]], int(m.group(1))).date()
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", t or "")
    return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).date() if m else None


def cidade_uf(endereco, curto, loc_cidade):
    """'Rua X, 121, Apto 102, Pechincha, Rio De Janeiro, RJ, CEP: ...' -> (cidade, UF, bairro)."""
    m = re.search(r",\s*([^,]+?),\s*([A-Z]{2})\s*,?\s*(?:-?\s*CEP|$)", endereco or "")
    if m:
        partes = [x.strip() for x in endereco[:m.start()].split(",")]
        return limpa_cidade(m.group(1)), m.group(2), (partes[-1] if len(partes) >= 3 else None)
    m = re.search(r"(?:,|-)\s*([^,|/-]+?)\s*/\s*([A-Z]{2})\b", endereco or "")
    if m:
        antes = [x.strip() for x in endereco[:m.start()].split(",")]
        bairro = re.sub(r"(?i)^bairro\s+", "", antes[-1]) if len(antes) >= 2 else None
        return limpa_cidade(m.group(1)), m.group(2), bairro
    m = re.search(r"\|\s*([^|]+?)\s*[-/]\s*([A-Z]{2})\s*(?:\||$)", curto or "")
    if m:
        return m.group(1).strip(), m.group(2), None
    return loc_cidade, None, None


def montar(o, hoje, banco="Santander"):
    p = o.get("product") or {}
    a = o.get("auction") or {}
    tpl = campos_template(p)
    desc = texto_html(p.get("detailedDescription") or "")
    curto = (p.get("shortDesc") or "").strip()
    endereco = tpl.get("endereco") or achar(r"Endere[çc]o Completo\s*\n?([^\n]+)", desc) or achar(r"Localiza[çc][ãa]o:\s*([^\n]+)", desc)
    cidade, uf, bairro = cidade_uf(endereco, curto, (p.get("location") or {}).get("city"))
    sub = ((p.get("subCategory") or {}).get("description") or "")
    tipo = {"Apartamentos": "Apartamento", "Casas": "Casa"}.get(sub, sub or None)
    if not tipo and re.match(r"(?i)apto|apartamento", curto):
        tipo = "Apartamento"
    cond = tpl.get("condicoesdepagamento") or achar(r"FORMA DE PAGAMENTO:\s*([^\n]+)", desc) or achar(r"Condi[çc][õo]es de Pagamento\s*\n([^\n]+)", desc)
    lance = (o.get("offerDetail") or {}).get("initialBidValue") or o.get("price")
    avaliacao = num_br(achar(r"Valor (?:Avaliado|de Avalia[çc][ãa]o):\s*R\$\s*([\d.,]+)", desc))
    alvo = num_br(achar(r"Valor Alvo:\s*R\$\s*([\d.,]+)", desc))
    v2 = d2 = h2 = None
    m2 = re.search(r"2[ªa]\s*Pra[çc]a:(.*?)Valor M[íi]nimo de Venda de R\$\s*([\d.,]+)", desc, re.I | re.S)
    if m2:
        v2 = num_br(m2.group(2))
        fech = re.search(r"Fechamento:\s*([^\n]*?)(?:,\s*a partir das\s*(\d{1,2}h\d{0,2}))?\s*com", m2.group(1) + " com", re.I)
        if fech:
            d2, h2 = data_pt(fech.group(1)), fech.group(2)
    try:
        fim = datetime.strptime(o.get("endDate") or a.get("endDate"), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).astimezone(BRT)
    except Exception:  # noqa
        fim = None
    ocup = tpl.get("situacao") or achar(r"Status da Ocupa[çc][ãa]o:\s*([A-Za-zçãÇÃ]+)", desc) or achar(r"Im[óo]vel (ocupado|desocupado)", desc)
    ocup = ocup.capitalize() if ocup else None
    vagas = achar(r"Vagas?:\s*(\d+)", desc) or achar(r"(\d+)\s*vagas?", curto + " " + desc)
    deb = tpl.get("responsabilidadedopagamentodosdebitos")
    deb_txt = achar(r"(OS D[ÉE]BITOS[^\n.]*(?:\.|$))", desc) or (f"Débitos: {deb}" if deb else None)
    area = (tpl.get("areaprivativa") or tpl.get("areatotal") or num_br(achar(r"[ÁA]rea Privativa:\s*([\d.,]+)", desc))
            or num_br(achar(r"(\d+(?:[.,]\d+)?)\s*m(?:²|2)\b", curto)))
    if not cond:  # sem o campo: procura a regra no texto do lote, no título ou no evento
        ctx = desc + "\n" + curto + "\n" + texto_html(a.get("fullDescription") or "")
        cond = (achar(r"([^\n]*financ[^\n]*)", ctx) or achar(r"([^\n|]*(?:entrada|sinal) de \d{1,2}\s*%[^\n|]*)", ctx))
    fin, fin_tipo = classifica_pagamento(cond, banco)
    d = {
        "banco": banco, "fonte": "SOLD", "numero_bem": f"{PREFIXO[banco]}{o['id']}", "id_oferta": o["id"],
        "uf": uf, "cidade": cidade, "bairro": bairro, "endereco": endereco, "empreendimento": None,
        "tipo": tipo, "area_privativa": float(area) if area not in (None, "") else None, "area_total": None,
        "quartos": int(tpl["quartos"]) if str(tpl.get("quartos", "")).isdigit() else (int(achar(r"Dormit[óo]rios:\s*(\d+)", desc)) if achar(r"Dormit[óo]rios:\s*(\d+)", desc) else None),
        "vaga": ("sim" if int(vagas) > 0 else "não") if vagas else None,
        "lance_minimo": lance, "avaliacao": avaliacao, "valor_alvo": alvo,
        "desconto_pct": round(1 - lance / avaliacao, 4) if lance and avaliacao else (round(float(tpl["desagio"]) / 100, 4) if tpl.get("desagio") else None),
        "modalidade": f"{a.get('desc') or 'Leilão'} (SOLD)", "descricao": curto,
        "financiamento": fin, "financiamento_tipo": fin_tipo, "financiamento_texto": cond, "financiamento_lista": None,
        "fgts": "FGTS" in norm(cond) or "FGTS" in norm(a.get("fullDescription")),
        "data_leilao": fim.date().isoformat() if fim else None, "hora_leilao": fim.strftime("%Hh%M") if fim else None,
        "lance_2_leilao": v2, "data_2_leilao": d2.isoformat() if d2 else None, "hora_2_leilao": h2, "licitacao": f"{a.get('desc')} — evento {a.get('id')}", "lote": str(o.get("lotNumber") or "") or None,
        "leiloeiro": (a.get("auctioneer") or "").title() or None,
        "matricula": tpl.get("matricula") or achar(r"Matr[íi]cula(?:\(s\))?(?: n[ºo°])?:\s*([\d.\-]+)", desc),
        "oficio": achar(r"Cart[óo]rio(?: de Registro)?:\s*([^\n.]+)", desc) or achar(r"RGI:\s*([^\n]+)", desc),
        "regra_condominio": deb_txt, "regra_tributos": deb_txt, "averbacao_leiloes": None, "ocupacao": ocup,
        "comissao_pct": ((o.get("commercialCondition") or {}).get("auctioneerCommissionPercent") or None),
        "anexos": [{"nome": (x.get("originalFileName") or "").split("/")[-1], "link": x.get("link")} for x in (p.get("attachments") or [])][:8],
        "link": f"https://www.sold.com.br/oferta/{slug(curto)}-{o['id']}",
    }
    al = []
    if d["ocupacao"] is None: al.append("Ocupação não informada")
    elif d["ocupacao"] == "Ocupado": al.append("Ocupado")
    if d["vaga"] is None: al.append("Vaga não informada")
    if re.search(r"Venda Condicional", desc, re.I):
        al.append("Venda condicional: o vendedor aprova o valor" + (f" (valor alvo R$ {alvo:,.0f})".replace(",", ".") if alvo else ""))
    if re.search(r"direito de prefer[êe]ncia", desc, re.I): al.append("Direito de preferência do fiduciante")
    acao = achar(r"(Recai sobre o im[óo]vel[^\n]+)", desc)
    if acao: al.append(acao[:160])
    if fin_tipo == "direto do banco":
        ctx = (cond or "") + "\n" + curto + "\n" + desc + "\n" + texto_html(a.get("fullDescription") or "")
        ent = achar(r"(?:entrada|sinal)(?: m[íi]nim[ao])?(?: de)?\s*(\d{1,2})\s*%", ctx)
        juros = achar(r"juros de\s*(\d{1,2}(?:[.,]\s?\d{1,2})?)\s*%", ctx) or achar(r"(\d{1,2}(?:[.,]\s?\d{1,2})?)\s*%\s*(?:a\.?\s*a\b|ao ano)", ctx)
        juros = re.sub(r"\s", "", juros) if juros else None
        al.append(f"Financiamento direto do {banco}" + (f": entrada mínima {ent}%" if ent else "")
                  + (f", juros {juros}% a.a." if juros else "") + (" + IPCA" if "IPCA" in norm(ctx) else "")
                  + " — confirmar no edital (percentual financiável e se vale para imóvel ocupado)")
        if ent:
            d["entrada_min_pct"] = int(ent) / 100
        if juros:
            d["juros_aa"] = round(float(juros.replace(",", ".")) / 100, 4)
            d["juros_indice"] = "IPCA" if "IPCA" in norm(ctx) else None
    al.append("Comissão do leiloeiro: confirmar no edital")
    if v2: al.append("2º leilão" + (" em " + d2.strftime("%d/%m") if d2 else "") + ": R$ " + f"{v2:,.0f}".replace(",", "."))
    d["alertas"] = al
    return d


def buscar(pg, url):
    r = pg.evaluate("async (u) => { const r = await fetch(u, {headers: {'Accept': 'application/json'}});"
                    " return {status: r.status, txt: await r.text()}; }", url)
    if r["status"] != 200:
        raise RuntimeError(f"API da SOLD respondeu {r['status']}")
    return json.loads(r["txt"])


def coletar(crit, hoje, cidades, diag, bancos=("Santander", "Inter")):
    """Devolve (imoveis, {banco: contagens}). cidades = {"SP": set(norm), "RJ": set(norm)}."""
    from playwright.sync_api import sync_playwright
    lmin, lmax = crit.get("lance_min", 0), crit.get("lance_max", 10**12)
    so_apto = crit.get("somente_apartamentos", True)
    conts = {b: {"ofertas_sold": 0, "ofertas_banco": 0, "candidatos": 0, "sem_financiamento": 0, "fora_cidade": 0,
                 "fora_faixa": 0, "fora_tipo": 0} for b in bancos}
    condicoes = {b: Counter() for b in bancos}
    ofertas, imoveis = [], []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(locale="pt-BR", timezone_id="America/Sao_Paulo")
        ctx.route("**/*", lambda r: r.abort() if r.request.resource_type in ("image", "media", "font") else r.continue_())
        pg = ctx.new_page()
        pg.goto(SOLD, wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(3000)
        pag, total = 1, None
        while True:
            d = buscar(pg, API.format(tam=TAM, pag=pag))
            total = d.get("total") or 0
            ofertas += d.get("offers") or []
            if len(ofertas) >= total or not d.get("offers") or pag >= 40:
                break
            pag += 1
            time.sleep(PAUSA)
        b.close()
    diag["sold_paginas"] = pag
    for c in conts.values():
        c["ofertas_sold"] = len(ofertas)
    for o in ofertas:
        banco = banco_de(o)
        if banco not in conts:
            continue
        cont = conts[banco]
        cont["ofertas_banco"] += 1
        d = montar(o, hoje, banco)
        condicoes[banco][(d.get("financiamento_texto") or "(sem condição)")[:300]] += 1
        if norm(d["cidade"]) not in cidades.get(d["uf"] or "", set()):
            cont["fora_cidade"] += 1; continue
        valores = [v for v in (d["lance_minimo"], d.get("lance_2_leilao")) if v]
        if not any(lmin <= v <= lmax for v in valores):
            cont["fora_faixa"] += 1; continue
        if so_apto and d["tipo"] != "Apartamento":
            cont["fora_tipo"] += 1; continue
        if FRACAO.search(norm(d["descricao"])):
            cont["fora_tipo"] += 1; continue
        cont["candidatos"] += 1
        if d["financiamento"] is False:
            cont["sem_financiamento"] += 1
        imoveis.append(d)
    for b, c in conts.items():
        c[b.lower()] = c["ofertas_banco"]  # compatível com o importador (contagens.santander)
        c["condicoes"] = dict(condicoes[b].most_common(8))
    return imoveis, conts
