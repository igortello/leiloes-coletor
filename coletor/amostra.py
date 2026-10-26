"""Sonda temporária: salva HTML renderizado, respostas JSON (XHR/fetch) e requisições
de rede de algumas páginas em amostras/, para desenhar um coletor. Não grava nada no portal."""
import json, os, sys, time
from playwright.sync_api import sync_playwright

OUT = "amostras"
os.makedirs(OUT, exist_ok=True)
URLS = sys.argv[1:] or os.environ.get("URLS", "").split()
rede, n = [], [0]


def resposta(r):
    req = r.request
    if req.resource_type not in ("xhr", "fetch"):
        return
    item = {"url": req.url, "metodo": req.method, "post": (req.post_data or "")[:3000], "status": r.status,
            "tipo": r.headers.get("content-type", "")}
    if "json" in item["tipo"] or "frazao" in req.url:
        try:
            n[0] += 1
            nome = f"{OUT}/resp_{n[0]:03d}.json"
            open(nome, "w", encoding="utf-8").write(r.text())
            item["arquivo"] = nome
        except Exception as e:  # noqa
            item["erro"] = str(e)
    rede.append(item)


with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(locale="pt-BR", user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36")
    pg = ctx.new_page()
    pg.on("response", resposta)
    for i, u in enumerate(URLS):
        if u.startswith("json:"):  # GET de API pública a partir da página aberta (mesmo contexto do site)
            try:
                txt = pg.evaluate("async (u) => { const r = await fetch(u); return r.status + '\\n' + await r.text(); }", u[5:])
            except Exception as e:  # noqa
                txt = "erro " + str(e)
            open(f"{OUT}/{i:02d}.json.txt", "w", encoding="utf-8").write(u[5:] + "\n" + txt)
            time.sleep(1.5)
            continue
        try:
            pg.goto(u, wait_until="networkidle", timeout=90000)
            pg.wait_for_timeout(4000)
            for _ in range(3):  # rola para disparar carregamento sob demanda
                pg.mouse.wheel(0, 4000); pg.wait_for_timeout(1500)
            for _ in range(int(os.environ.get("CLIQUES", "2"))):  # botão "Carregar mais" (Zuk)
                bt = pg.locator("#btn_carregarMais")
                if not bt.count() or not bt.is_visible():
                    break
                bt.click(); pg.wait_for_timeout(3500)
        except Exception as e:  # noqa
            print("erro", u, e)
        open(f"{OUT}/{i:02d}.html", "w", encoding="utf-8").write(f"<!-- {u} -->\n" + pg.content())
        open(f"{OUT}/{i:02d}.txt", "w", encoding="utf-8").write(f"{u}\n{pg.title()}\n" + pg.inner_text("body"))
        time.sleep(2)
    b.close()
json.dump(rede, open(f"{OUT}/rede.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(len(rede), "requisições;", n[0], "respostas JSON")
