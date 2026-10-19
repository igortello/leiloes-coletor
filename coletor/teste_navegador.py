import asyncio, json, os, time
from playwright.async_api import async_playwright
OUT = {}
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx = await b.new_context(accept_downloads=True, locale="pt-BR", timezone_id="America/Sao_Paulo",
              user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
              viewport={"width":1366,"height":768})
        await ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        page = await ctx.new_page()
        for nome, url in [("home","https://venda-imoveis.caixa.gov.br/sistema/download-lista.asp"),
                          ("detalhe","https://venda-imoveis.caixa.gov.br/sistema/detalhe-imovel.asp?hdnimovel=1787702384777")]:
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                for _ in range(6):
                    await page.wait_for_timeout(5000)
                    t = await page.title()
                    if "Radware" not in t and "CAPTCHA" not in t.upper(): break
                html = await page.content()
                OUT[nome] = {"titulo": await page.title(), "url_final": page.url, "bytes": len(html),
                             "tem_financiamento": "financiamento" in html.lower(), "inicio": html[:400]}
            except Exception as e:
                OUT[nome] = {"erro": repr(e)}
        await page.goto("https://venda-imoveis.caixa.gov.br/sistema/download-lista.asp", wait_until="domcontentloaded")
        await page.wait_for_timeout(4000)
        try:
            js = """async (u) => { const r = await fetch(u, {credentials:'include'}); const b = new Uint8Array(await r.arrayBuffer());
                    let s=''; for (let i=0;i<Math.min(b.length,400);i++) s+=String.fromCharCode(b[i]); return {status:r.status, tipo:r.headers.get('content-type'), bytes:b.length, inicio:s}; }"""
            OUT["csv_fetch_pagina"] = await page.evaluate(js, "https://venda-imoveis.caixa.gov.br/listaweb/Lista_imoveis_SP.csv")
        except Exception as e:
            OUT["csv_fetch_pagina"] = {"erro": repr(e)}
        try:
            async with page.expect_download(timeout=60000) as dl:
                await page.evaluate("u => { const a=document.createElement('a'); a.href=u; a.download=''; document.body.appendChild(a); a.click(); }", "https://venda-imoveis.caixa.gov.br/listaweb/Lista_imoveis_RJ.csv")
            d = await dl.value
            path = await d.path(); data = open(path,'rb').read()
            OUT["csv_download_clique"] = {"bytes": len(data), "inicio": data[:300].decode("latin-1","ignore")}
        except Exception as e:
            OUT["csv_download_clique"] = {"erro": repr(e)}
        try:
            html = await page.content()
            import re
            OUT["form_download"] = re.findall(r"<(?:form|select|option|input|button)[^>]{0,200}>", html)[:40]
        except Exception as e:
            OUT["form_download"] = repr(e)
        try:
            r = await ctx.request.get("https://venda-imoveis.caixa.gov.br/listaweb/Lista_imoveis_SP.csv", timeout=60000)
            body = await r.body()
            OUT["csv"] = {"status": r.status, "tipo": r.headers.get("content-type"), "bytes": len(body), "inicio": body[:300].decode("latin-1","ignore")}
        except Exception as e:
            OUT["csv"] = {"erro": repr(e)}
        OUT["cookies"] = [c["name"] for c in await ctx.cookies()]
        await b.close()
asyncio.run(main())
os.makedirs("saida", exist_ok=True)
json.dump(OUT, open("saida/teste_navegador.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps({k:{kk:(vv if kk!="inicio" else vv[:80]) for kk,vv in v.items()} if isinstance(v,dict) else v for k,v in OUT.items()}, ensure_ascii=False, indent=1))
