"""Sonda temporária da Frazão Leilões: lista todos os lotes ativos (busca pública do site)
e salva algumas páginas de lote, para desenhar o coletor. Não grava nada no portal."""
import json, os, re, time, traceback
from collections import Counter
from playwright.sync_api import sync_playwright

OUT = "amostras"
os.makedirs(OUT, exist_ok=True)
BASE = "https://www.frazaoleiloes.com.br"
BUSCA = ("/Sale/SearchLotResult?uf=&cidade=&bairro=&tipoimovel=&subtipoImovel=&area=&preco=&term=&start={start}&limit={lim}"
         "&page={page}&vendedor=&categoria=&subcategoria=&tipolote=&documentacaolote=&loteAtivo=true&ExibirInternosPrimeiro=true"
         "&end=&cep=&segmento=&modalidadeId=&litoral=false&__RequestVerificationToken={tok}")

LOG = open(f"{OUT}/log.txt", "w", encoding="utf-8")
def log(*a):
    print(*a, flush=True); LOG.write(" ".join(map(str, a)) + "\n"); LOG.flush()
com = Counter()
try:
  with sync_playwright() as p:
      b = p.chromium.launch(headless=True)
      ctx = b.new_context(locale="pt-BR", user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36")
      pg = ctx.new_page()
      pg.goto(BASE + "/leiloes", wait_until="domcontentloaded", timeout=60000)
      tok = pg.evaluate("() => (document.querySelector('input[name=__RequestVerificationToken]')||{}).value || ''")
      log("token", bool(tok)); pg.wait_for_timeout(4000)
      cards, info = [], []
      for tentativa in [dict(start=0, lim=50, page=1), dict(start=50, lim=50, page=2), dict(start=0, lim=500, page=1)]:
          url = BASE + BUSCA.format(tok=tok, **tentativa)
          r = pg.evaluate("async (u) => { const r = await fetch(u, {headers:{'X-Requested-With':'XMLHttpRequest'}}); return r.status + '\\n' + await r.text(); }", url)
          st, txt = r.split("\n", 1)
          ids = re.findall(r'data-lote-id="(\d+)"', txt)
          info.append({**tentativa, "status": st, "n": len(ids), "primeiro": ids[:3], "total": re.findall(r'total="(\d+)"', txt)[:1]})
          open(f"{OUT}/busca_{tentativa['start']}_{tentativa['lim']}.html", "w", encoding="utf-8").write(txt)
          time.sleep(2)
      log(json.dumps(info))
      grande = open(f"{OUT}/busca_0_500.html", encoding="utf-8").read()
      blocos = grande.split('id="card-lote"')[1:]
      com = Counter()
      exemplos = {}
      for c in blocos:
          v = re.search(r'alt="Logo ([^"]*)"', c)
          v = v.group(1) if v else "?"
          com[v] += 1
          href = re.search(r'href="(/lote/[^"]+)"', c)
          if href and v not in exemplos:
              exemplos[v] = href.group(1)
      json.dump({"info": info, "comitentes": com.most_common(), "exemplos": exemplos}, open(f"{OUT}/resumo.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
      alvo = [h for v, h in exemplos.items() if re.search(r"SANTANDER|ITA|INTER|BRADESCO", v.upper())][:4] or list(exemplos.values())[:3]
      for i, h in enumerate(alvo):
          try:
              pg.goto(BASE + h, wait_until="domcontentloaded", timeout=60000)
              pg.wait_for_timeout(3000)
          except Exception as e:  # noqa
              log("erro", h, e)
          open(f"{OUT}/lote_{i}.html", "w", encoding="utf-8").write(f"<!-- {h} -->\n" + pg.content())
          open(f"{OUT}/lote_{i}.txt", "w", encoding="utf-8").write(f"{h}\n" + pg.inner_text("body"))
          time.sleep(2)
      b.close()
except Exception:
    log(traceback.format_exc())
log(com.most_common())
