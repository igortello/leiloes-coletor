# leiloes-coletor

Coletor do Portal de Leilões. A action "Coleta Caixa" baixa as listas de imóveis da Caixa (SP e RJ), aplica os critérios do portal, lê o anúncio de cada candidato e publica `resultado.json` como artifact da execução. Quem dispara e importa o resultado no portal é a tarefa "Coleta do Portal de Leilões" no Claude.
