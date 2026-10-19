"""Coletor do Portal de Leilões — imóveis Caixa (SP/RJ).

Baixa as listas oficiais da Caixa, aplica os critérios do portal, abre o
anúncio de cada candidato e grava saida/resultado.json.
Só biblioteca padrão. Critérios: variável de ambiente CRITERIOS (JSON) ou criterios.json.
"""
import csv, io, json, os, re, sys, time, unicodedata, urllib.request
from datetime import datetime, date, timezone, timedelta

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
LISTA = "https://venda-imoveis.caixa.gov.br/listaweb/Lista_imoveis_{uf}.csv"
DETALHE = "https://venda-imoveis.caixa.gov.br/sistema/detalhe-imovel.asp?hdnimovel={num}"
BRT = timezone(timedelta(hours=-3))
PAUSA = float(os.environ.get("PAUSA", "0.7"))
DIAG = {}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip().upper()


def baixar(url, tentativas=3):
    erro = None
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
                DIAG[url[-60:]] = {"status": r.status, "tipo": r.headers.get("Content-Type"), "bytes": len(data),
                                   "inicio": data[:300].decode("latin-1", "ignore")}
                return data
        except Exception as e:  # noqa
            erro = e
            body = getattr(e, "read", lambda: b"")()[:300] if hasattr(e, "read") else b""
            DIAG[url[-60:]] = {"erro": repr(e), "inicio": body.decode("latin-1", "ignore")}
            time.sleep(2 + 3 * i)
    raise RuntimeError(f"falha ao baixar {url}: {erro}")


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


COLS = {"numero": ("N DO IMOVEL", "NO DO IMOVEL", "NUMERO DO IMOVEL", "N DO IMOVEL"),
        "uf": ("UF",), "cidade": ("CIDADE",), "bairro": ("BAIRRO",), "endereco": ("ENDERECO",),
        "preco": ("PRECO",), "avaliacao": ("VALOR DE AVALIACAO",), "desconto": ("DESCONTO",),
        "descricao": ("DESCRICAO",), "modalidade": ("MODALIDADE DE VENDA", "MODALIDADE"), "link": ("LINK DE ACESSO", "LINK")}


def ler_lista(raw):
    txt = raw.decode("latin-1")
    linhas = txt.splitlines()
    ini = next((i for i, l in enumerate(linhas) if "UF" in norm(l) and "CIDADE" in norm(l) and ";" in l), None)
    if ini is None:
        raise RuntimeError("cabeçalho da lista da Caixa não encontrado (formato mudou?)")
    leitor = csv.reader(io.StringIO("\n".join(linhas[ini:])), delimiter=";")
    cab = [norm(c).replace("º", "").replace("°", "") for c in next(leitor)]
    cab = [re.sub(r"[^A-Z ]", "", c).strip() for c in cab]
    idx = {}
    for k, nomes in COLS.items():
        for j, c in enumerate(cab):
            if c in nomes or (k == "numero" and c.startswith("N") and "IMOVEL" in c):
                idx[k] = j; break
    falt = [k for k in ("numero", "uf", "cidade", "preco") if k not in idx]
    if falt:
        raise RuntimeError(f"colunas ausentes na lista: {falt}; cabeçalho={cab}")
    out = []
    for row in leitor:
        if not row or len(row) < len(idx):
            continue
        g = lambda k: row[idx[k]].strip() if k in idx and idx[k] < len(row) else ""
        numero = re.sub(r"\D", "", g("numero"))
        if not numero:
            continue
        out.append({"numero": numero, "uf": g("uf").upper(), "cidade": g("cidade"), "bairro": g("bairro"),
                    "endereco": g("endereco"), "preco": num_br(g("preco")), "avaliacao": num_br(g("avaliacao")),
                    "desconto": num_br(g("desconto")), "descricao": g("descricao"), "modalidade": g("modalidade")})
    return out


FRACAO = re.compile(r"FRACAO|PARTE IDEAL|DIREITOS? SOBRE|USUFRUTO|NUA[- ]PROPRIEDADE|\d+(?:[.,]\d+)?\s*%", re.I)


def desc_campos(d):
    n = norm(d)
    tipo = (d.split(",")[0].strip() if d else None) or None
    f = lambda pat: (lambda m: float(m.group(1).replace(",", ".")) if m else None)(re.search(pat, n))
    q = re.search(r"(\d+)\s*QTO", n)
    v = re.search(r"(\d+)\s*VAGA", n)
    vaga = None
    if v:
        vaga = "sim" if int(v.group(1)) > 0 else "não"
    elif "VAGA" in n:
        vaga = "sim"
    ap = f(r"([\d.,]+)\s*DE AREA PRIVATIVA")
    at = f(r"([\d.,]+)\s*DE AREA TOTAL")
    return {"tipo": tipo, "area_privativa": ap or None, "area_total": at or None,
            "quartos": int(q.group(1)) if q else None, "vaga": vaga}


def texto(html):
    h = html.decode("latin-1", "ignore") if b"charset=utf-8" not in html[:3000].lower() else html.decode("utf-8", "ignore")
    h = re.sub(r"(?is)<(script|style).*?</\1>", " ", h)
    h = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h\d|span|tr|td|strong|b|label)>", "\n", h)
    h = re.sub(r"<[^>]+>", " ", h)
    import html as _h
    h = _h.unescape(h)
    return "\n".join(l for l in (re.sub(r"[ \t\xa0]+", " ", x).strip() for x in h.splitlines()) if l)


def achar(pat, t, grupo=1):
    m = re.search(pat, t, re.I)
    return m.group(grupo).strip() if m else None


def detalhe_campos(t, hoje):
    fin = achar(r"(Permite financiamento[^\n]*)", t)
    datas = []
    for m in re.finditer(r"Data d[oa]s?\s*([^\n]{0,40}?)\s*[-:]\s*(\d{2}/\d{2}/\d{4})(?:\s*[-–]\s*(\d{1,2}h\d{0,2}))?", t, re.I):
        try:
            d = datetime.strptime(m.group(2), "%d/%m/%Y").date()
        except ValueError:
            continue
        datas.append((d, m.group(3), m.group(1)))
    futuras = sorted([x for x in datas if x[0] >= hoje], key=lambda x: x[0])
    escolhida = futuras[0] if futuras else None
    ocup = achar(r"\b(Desocupado|Ocupado)\b", t)
    return {
        "financiamento": bool(fin), "financiamento_texto": fin,
        "fgts": bool(re.search(r"Permite utiliza[çc][ãa]o de FGTS", t, re.I)),
        "data_leilao": escolhida[0].isoformat() if escolhida else None,
        "hora_leilao": escolhida[1] if escolhida else None,
        "licitacao": achar(r"Edital:\s*([^\n]+)", t),
        "lote": achar(r"N[úu]mero do item:\s*(\d+)", t),
        "leiloeiro": achar(r"Leiloeiro\(a\):\s*([^\n]+)", t),
        "matricula": achar(r"Matr[íi]cula\(s\):\s*([\d.\- ]+)", t),
        "oficio": achar(r"Of[íi]cio:\s*(\d+)", t),
        "regra_condominio": achar(r"Condom[íi]nio:\s*([^\n]+)", t),
        "regra_tributos": achar(r"Tributos:\s*([^\n]+)", t),
        "averbacao_leiloes": achar(r"Averba[çc][ãa]o dos leil[õo]es negativos:\s*([^\n]+)", t),
        "ocupacao": ocup.capitalize() if ocup else None,
    }


def main():
    crit = json.loads(os.environ.get("CRITERIOS") or open("criterios.json", encoding="utf-8").read())
    lmin, lmax = crit.get("lance_min", 0), crit.get("lance_max", 10**12)
    cidades = {"SP": {norm(c) for c in crit.get("cidades_sp", [])}, "RJ": {norm(c) for c in crit.get("cidades_rj", [])}}
    hoje = datetime.now(BRT).date()
    os.makedirs("saida", exist_ok=True)
    cont = {"na_lista": 0, "candidatos": 0, "anuncios_ok": 0, "falhas": 0}
    candidatos = []
    for uf in ("SP", "RJ"):
        linhas = ler_lista(baixar(LISTA.format(uf=uf)))
        cont["na_lista"] += len(linhas)
        for l in linhas:
            if norm(l["cidade"]) not in cidades[uf]:
                continue
            if l["preco"] is None or not (lmin <= l["preco"] <= lmax):
                continue
            if FRACAO.search(norm(l["descricao"])):
                continue
            candidatos.append(l)
    cont["candidatos"] = len(candidatos)
    print(f"{cont['na_lista']} imóveis nas listas; {len(candidatos)} candidatos", flush=True)
    imoveis = []
    for i, l in enumerate(candidatos, 1):
        try:
            t = texto(baixar(DETALHE.format(num=l["numero"]), tentativas=2))
            det = detalhe_campos(t, hoje)
            cont["anuncios_ok"] += 1
        except Exception as e:  # noqa
            print("falha", l["numero"], e, flush=True)
            cont["falhas"] += 1
            det = None
        time.sleep(PAUSA)
        dc = desc_campos(l["descricao"])
        d = {"banco": "Caixa", "numero_bem": l["numero"], "uf": l["uf"], "cidade": l["cidade"], "bairro": l["bairro"],
             "endereco": l["endereco"], "empreendimento": None, **dc,
             "lance_minimo": l["preco"], "avaliacao": l["avaliacao"],
             "desconto_pct": round(l["desconto"] / 100, 4) if l["desconto"] is not None else None,
             "modalidade": l["modalidade"], "descricao": l["descricao"],
             "link": DETALHE.format(num=l["numero"])}
        if det:
            d.update(det)
        al = []
        if det is None: al.append("Anúncio não lido")
        if d.get("ocupacao") is None: al.append("Ocupação não informada")
        elif d.get("ocupacao") == "Ocupado": al.append("Ocupado")
        if d.get("vaga") is None: al.append("Vaga não informada")
        av = norm(d.get("averbacao_leiloes"))
        if av and "AVERBADO" not in av.split(): al.append("Leilões negativos " + (d.get("averbacao_leiloes") or "").lower())
        if det and d.get("data_leilao") is None: al.append("Sem data (venda direta)")
        d["alertas"] = al
        imoveis.append(d)
        if i % 25 == 0:
            print(f"{i}/{len(candidatos)} anúncios", flush=True)
    res = {"gerado_em": datetime.now(timezone.utc).isoformat(), "hoje_brt": hoje.isoformat(), "criterios": crit,
           "contagens": cont, "imoveis": imoveis}
    with open("saida/resultado.json", "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False)
    print(json.dumps(cont), flush=True)
    if cont["candidatos"] and cont["anuncios_ok"] == 0:
        sys.exit("nenhum anúncio pôde ser lido — o site da Caixa pode estar bloqueando")


if __name__ == "__main__":
    import traceback
    os.makedirs("saida", exist_ok=True)
    try:
        main()
    except BaseException as e:  # registra o erro para quem importa o resultado
        with open("saida/erro.json", "w", encoding="utf-8") as f:
            json.dump({"em": datetime.now(timezone.utc).isoformat(), "erro": str(e),
                       "traceback": traceback.format_exc()[-4000:], "diagnostico": DIAG}, f, ensure_ascii=False)
        raise
