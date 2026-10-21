"""Sonda temporária do leilaoimovel.com.br: salva HTML, scripts e requisições de rede
em amostras/ para desenhar o coletor. Não grava nada no portal."""
import json, os, re, sys, time
from playwright.sync_api import sync_playwright

BASE = "https://www.leilaoimovel.com.br"
OUT = "amostras"
os.makedirs(OUT, exist_ok=True)
URLS = sys.argv[1:] or [
    "/encontre-seu-imovel",
    "/leilao-de-imoveis/sp",
    "/leilao-de-imovel/sao-paulo-sp",
    "/leilao-de-imoveis-tipo/apartamento",
    "/banco_leilao_de_imoveis/santander",
    "/imovel/sp/aracatuba/residencial-res-aires-2-quartos-1-vaga-na-garagem-area-de-servico-wc-sala-cozinha-imovel-caixa-economica-federal-cef-3071763-8787717110420-venda-direta-caixa",
    "/robots.txt",
]
rede = []
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(locale="pt-BR", user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36")
    pg = ctx.new_page()
    pg.on("request", lambda r: rede.append({"url": r.url, "metodo": r.method, "tipo": r.resource_type,
                                            "post": (r.post_data or "")[:2000]}) if r.resource_type in ("xhr", "fetch", "document") else None)
    scripts = set()
    for i, u in enumerate(URLS):
        try:
            pg.goto(BASE + u if u.startswith("/") else u, wait_until="networkidle", timeout=90000)
        except Exception as e:  # noqa
            print("erro", u, e)
        html = pg.content()
        open(f"{OUT}/{i:02d}.html", "w", encoding="utf-8").write(f"<!-- {u} -->\n" + html)
        for s in re.findall(r'<script[^>]+src="([^"]+)"', html):
            if "leilaoimovel" in s or s.startswith("/"):
                scripts.add(s)
        time.sleep(2)
    # primeira página de resultados: tenta abrir um imóvel de outro banco (não Caixa)
    for j, s in enumerate(sorted(scripts)):
        try:
            r = ctx.request.get(s if s.startswith("http") else BASE + s, timeout=60000)
            open(f"{OUT}/js_{j:02d}.js", "w", encoding="utf-8").write(f"// {s}\n" + r.text())
        except Exception as e:  # noqa
            print("js", s, e)
    b.close()
json.dump(rede, open(f"{OUT}/rede.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(len(rede), "requisições;", len(scripts), "scripts")
