"""Matrícula e edital dos imóveis da Caixa.

Os PDFs ficam no ramo `documentos` do repositório (acumulativo: cada coleta baixa só o que falta)
e cada imóvel do resultado.json ganha `documentos` com o caminho e o link raw do GitHub.

- Matrícula: uma por imóvel, em matricula/<UF>/<número do bem>.pdf (o mesmo caminho do site da Caixa).
- Edital: um por licitação (vale para todos os lotes), em edital/<arquivo do site>; Venda Online e
  Venda Direta Online usam o arquivo que o anúncio indicar.
"""
import base64, hashlib, json, os, re, time
from datetime import datetime, timezone

BASE = "https://venda-imoveis.caixa.gov.br"
MATRICULA = BASE + "/editais/matricula/{uf}/{num}.pdf"
REPO = os.environ.get("GITHUB_REPOSITORY", "igortello/leiloes-coletor")
RAW = "https://raw.githubusercontent.com/" + REPO + "/documentos/{caminho}"
MAX_BYTES = 20 * 1024 * 1024
PAUSA = float(os.environ.get("PAUSA_DOCS", "1.0"))

# ExibeDoc('/editais/...'), href="/editais/...", window.open('/editais/...')
_LINK = re.compile(r"""['"](/?editais/[^'"<>\s]+?\.(?:pdf|zip))['"]""", re.I)


def links_documentos(html):
    """Links de documentos no HTML do anúncio: {matricula_url, edital_url, outros_urls}."""
    vistos = []
    for m in _LINK.finditer(html or ""):
        p = "/" + m.group(1).lstrip("/")
        if p not in vistos:
            vistos.append(p)
    mat = next((p for p in vistos if "/matricula/" in p.lower()), None)
    outros = [p for p in vistos if p != mat]
    # o edital da licitação costuma ser o PDF direto em /editais/ (não em subpastas como /matricula/ ou /fotos/)
    edital = next((p for p in outros if re.fullmatch(r"/editais/[^/]+\.(pdf|zip)", p, re.I)), None) or (outros[0] if outros else None)
    return {"matricula_url": BASE + mat if mat else None,
            "edital_url": BASE + edital if edital else None,
            "outros_urls": [BASE + p for p in outros if p != edital] or None}


def _tipo(data):
    if data[:5] == b"%PDF-":
        return "pdf"
    if data[:2] == b"PK":
        return "zip"
    return None


def baixar(page, url):
    """Baixa pelo navegador (mesmos cookies do anti-robô). Devolve bytes ou levanta erro."""
    r = page.evaluate("""async (u) => { const r = await fetch(u, {credentials:'include'});
        if (!r.ok) return {status:r.status};
        const b = new Uint8Array(await r.arrayBuffer());
        if (b.length > %d) return {status:r.status, grande:b.length};
        let s=''; const n=0x8000;
        for (let i=0;i<b.length;i+=n) s += String.fromCharCode.apply(null, b.subarray(i,i+n));
        return {status:r.status, b64:btoa(s)}; }""" % MAX_BYTES, url)
    if r.get("grande"):
        raise RuntimeError(f"arquivo grande demais ({r['grande']} bytes)")
    if "b64" not in r:
        raise RuntimeError(f"HTTP {r.get('status')}")
    data = base64.b64decode(r["b64"])
    if not _tipo(data):
        ini = data[:200].decode("latin-1", "ignore")
        raise RuntimeError("não é PDF" + (" (anti-robô)" if "Radware" in data[:3000].decode("latin-1", "ignore") else "") + ": " + ini[:80])
    return data


def _slug(s):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_")


class Acervo:
    """Pasta com o checkout do ramo `documentos` e o índice dos arquivos."""
    def __init__(self, pasta):
        self.pasta = pasta
        os.makedirs(pasta, exist_ok=True)
        self.arq_indice = os.path.join(pasta, "indice.json")
        try:
            self.indice = json.load(open(self.arq_indice, encoding="utf-8"))
        except Exception:
            self.indice = {}
        self.novos = 0

    def tem(self, caminho):
        return caminho in self.indice and os.path.exists(os.path.join(self.pasta, caminho))

    def gravar(self, caminho, data, origem):
        dest = os.path.join(self.pasta, caminho)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(data)
        self.indice[caminho] = {"origem": origem, "bytes": len(data), "tipo": _tipo(data),
                                "sha256": hashlib.sha256(data).hexdigest(),
                                "baixado_em": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self.novos += 1

    def salvar_indice(self):
        with open(self.arq_indice, "w", encoding="utf-8") as f:
            json.dump(self.indice, f, ensure_ascii=False, indent=0, sort_keys=True)

    def ref(self, caminho):
        i = self.indice[caminho]
        return {"caminho": caminho, "url": RAW.format(caminho=caminho), "origem": i["origem"],
                "tipo": i.get("tipo"), "bytes": i["bytes"], "sha256": i["sha256"], "baixado_em": i["baixado_em"]}


def caminho_matricula(d):
    return f"matricula/{d['uf']}/{d['numero_bem']}.pdf"


def caminho_edital(url):
    nome = _slug(url.rsplit("/", 1)[-1])
    return "edital/" + nome


def coletar(nav, imoveis, acervo, detalhe_url, limite_s, diag):
    """Baixa matrícula e edital dos imóveis da Caixa com financiamento. Não levanta erro."""
    t0 = time.time()
    cont = {"imoveis": 0, "matriculas_baixadas": 0, "matriculas_ja_tinha": 0, "editais_baixados": 0,
            "editais_ja_tinha": 0, "anuncios_reabertos": 0, "sem_edital": 0, "falhas": 0, "nao_feitos_por_tempo": 0}
    falhas = []
    editais_tentados = {}
    alvo = [d for d in imoveis if d.get("banco") == "Caixa" and d.get("financiamento") and d.get("numero_bem")]
    cont["imoveis"] = len(alvo)
    page = nav.page
    for d in alvo:
        if time.time() - t0 > limite_s:
            cont["nao_feitos_por_tempo"] += 1
            continue
        docs = {}
        # links do anúncio: vêm da leitura desta coleta ou da anterior; sem eles, reabrir o anúncio
        if not d.get("_links_lidos"):   # anúncio lido por coleta antiga, sem os links: reabrir uma vez
            try:
                nav.abrir(detalhe_url.format(num=d["numero_bem"]))
                page.wait_for_timeout(1500)
                d.update(links_documentos(page.content()), _links_lidos=True); cont["anuncios_reabertos"] += 1
            except Exception as e:  # noqa
                falhas.append({"numero": d["numero_bem"], "etapa": "anúncio", "erro": str(e)[:200]})
        # matrícula
        cm = caminho_matricula(d)
        if acervo.tem(cm):
            cont["matriculas_ja_tinha"] += 1
        else:
            url = d.get("matricula_url") or MATRICULA.format(uf=d["uf"], num=d["numero_bem"])
            try:
                acervo.gravar(cm, baixar(page, url), url); cont["matriculas_baixadas"] += 1
                time.sleep(PAUSA)
            except Exception as e:  # noqa
                cont["falhas"] += 1
                falhas.append({"numero": d["numero_bem"], "etapa": "matrícula", "url": url, "erro": str(e)[:200]})
        if acervo.tem(cm):
            docs["matricula"] = acervo.ref(cm)
        # edital (um por arquivo; vários lotes da mesma licitação apontam para o mesmo)
        eu = d.get("edital_url")
        if eu:
            ce = caminho_edital(eu)
            if acervo.tem(ce):
                if ce not in editais_tentados:
                    cont["editais_ja_tinha"] += 1
            elif ce not in editais_tentados:
                try:
                    acervo.gravar(ce, baixar(page, eu), eu); cont["editais_baixados"] += 1
                    time.sleep(PAUSA)
                except Exception as e:  # noqa
                    cont["falhas"] += 1
                    falhas.append({"numero": d["numero_bem"], "etapa": "edital", "url": eu, "erro": str(e)[:200]})
            editais_tentados[ce] = True
            if acervo.tem(ce):
                docs["edital"] = acervo.ref(ce)
        else:
            cont["sem_edital"] += 1
        if docs:
            d["documentos"] = docs
    acervo.salvar_indice()
    diag["documentos_falhas"] = falhas[:30]
    cont["segundos"] = int(time.time() - t0)
    return cont
