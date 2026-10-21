# leiloes-coletor

Coletor do Portal de Leilões. A action "Coleta Caixa e Santander" (`coleta.yml`) lê duas fontes e publica `resultado.json` no ramo `resultados`:

- **Caixa:** baixa as listas oficiais (SP e RJ), aplica os critérios do portal e lê o anúncio de cada candidato (navegador real, por causa do anti-robô da Caixa).
- **Santander (SOLD):** lê, pela mesma API pública que o site www.sold.com.br usa, as ofertas de imóveis abertas na SOLD e fica só com as do Banco Santander. A forma de pagamento vem do campo "Condições de Pagamento" de cada lote. Os leilões "Santander Oportunidades" aceitam financiamento em até 420 meses; os de alienação fiduciária têm sido só à vista. Ids no portal: `S<id da oferta>`.

Input `fontes` (padrão `caixa,santander`) escolhe as fontes. Uma falha no Santander não derruba a coleta da Caixa: fica registrada em `resultado.fontes.santander`.

Quem dispara e importa o resultado no portal é a tarefa "Coleta do Portal de Leilões" no Claude.

Fontes avaliadas e descartadas (21/10/2026): leilaoimovel.com.br, superbid.net (verificação anti-robô da Cloudflare), santanderimoveis.com.br (bloqueio de servidores), Zuk (lotes do Santander só à vista), Bradesco (sem financiamento bancário; decisão do usuário).
