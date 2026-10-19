# Career Automation MVP — fluxo diário por vaga com observabilidade

Status: ready-for-agent

## Problem Statement

O cronjob diário de candidaturas é frágil e lento. Hoje o Hermes acorda um agente LLM com um prompt longo, e esse agente decide passo a passo qual comando executar. O orquestrador é o modelo, não o código. Isso torna a rodada cara, imprevisível e difícil de depurar.

O fluxo também é batch: primeiro coleta todas as vagas, depois filtra todas, depois enriquece todas as JDs e só então começa a aplicar. Na rodada de 19/10, 1.950 cards viraram 344 vagas únicas, 129 shortlist e apenas 12 JDs lidas; 4 eram elegíveis e nenhuma candidatura foi enviada porque o upload de CV congelou o renderer. Não há screenshot, vídeo ou artefato por vaga para mostrar onde travou.

O resultado é que a meta de 20 candidaturas verificadas por dia não é atingida, e quando um formulário pede uma resposta desconhecida o fluxo inteiro vai para o Telegram e exige aprovação repetida de comandos.

## Solution

Criar uma CLI determinística que executa o fluxo de ponta a ponta por vaga. O sistema novo roda em paralelo e isolado: o Hermes e o career-ops atuais permanecem intocados. O Hermes pode ser usado como leitura para entender o fluxo atual, mas integração, cron e allowlist ficam fora deste escopo.

O loop processa uma vaga por vez: pega o próximo candidato, deduplica, filtra título e localização, baixa somente a JD necessária, aplica elegibilidade, escolhe ou gera o CV, aplica, verifica o envio e incrementa o contador apenas quando o LinkedIn confirmar. O loop para ao atingir 20 envios verificados, ao esgotar o orçamento de tempo ou ao detectar limite do LinkedIn.

O CV é gerado por vaga quando não existe um CV suficientemente parecido. CVs gerados são indexados por competências, idioma, família e senioridade; um CV só é reutilizado quando o match é alto e nenhuma competência obrigatória falta.

Cada sessão diária produz screenshots das transições, logs estruturados, relatório Markdown/HTML e, opcionalmente, vídeo. As três últimas sessões ficam retidas. Em caso de renderer congelado, uma captura do sistema via `grim` registra a tela mesmo quando o CDP não responde.

Quando um formulário exigir resposta desconhecida, ele fica estacionado em uma aba, a vaga vira `waiting_input`, o loop continua na próxima vaga e o sistema expõe as perguntas pendentes em JSON. O usuário responde no Telegram, mas a ponte entre Hermes e CLI fica fora deste escopo; a CLI apenas oferece o comando de resposta para essa integração.

## User Stories

1. Como Renan, quero uma CLI determinística que o Hermes possa chamar, para que o LLM não seja mais o orquestrador de cada candidatura.
2. Como Renan, quero que o loop processe uma vaga por vez, para que o CV e a candidatura sejam feitos logo depois do filtro.
3. Como Renan, quero parar automaticamente ao atingir 20 candidaturas verificadas, para não gastar tempo além da meta.
4. Como Renan, quero que só contem candidaturas confirmadas pelo LinkedIn, para que o número de 20 seja real.
5. Como Renan, quero buscar vagas sob demanda, para não enriquecer centenas de JDs que nunca serão usadas.
6. Como Renan, quero reutilizar a fila de vagas não processadas de dias anteriores, para não recomeçar a descoberta do zero.
7. Como Renan, quero deduplicar por ID e por estado de candidatura, para não aplicar duas vezes na mesma vaga.
8. Como Renan, quero descartar títulos inadequados antes de baixar a JD, para reduzir tempo e chamadas ao LinkedIn.
9. Como Renan, quero filtrar localização e modelo de trabalho antes da aplicação, para não perder tempo com vagas híbridas fora de Recife.
10. Como Renan, quero que a elegibilidade seja determinística e auditável, para entender exatamente por que uma vaga foi descartada.
11. Como Renan, quero que cada vaga tenha um perfil estruturado com skills obrigatórias, preferidas, idioma, família e senioridade, para permitir cache e decisões consistentes.
12. Como Renan, quero gerar um CV novo quando não houver cache adequado, para manter a personalização.
13. Como Renan, quero reutilizar um CV quando o match for pelo menos 0.90 e nenhuma competência obrigatória faltar, para economizar tempo sem enviar um CV genérico.
14. Como Renan, quero que o CV não contenha nome de empresa, para que ele possa ser reutilizado com segurança entre vagas.
15. Como Renan, quero que a cover letter continue específica por vaga, para manter o conteúdo personalizado onde a empresa importa.
16. Como Renan, quero que cada CV tenha um identificador legível com família, stack, idioma, senioridade e fingerprint, para identificar rapidamente qual CV foi usado.
17. Como Renan, quero ver no relatório se o CV foi reutilizado ou gerado, para calibrar o threshold do cache.
18. Como Renan, quero aplicações estritamente sequenciais, para não corromper o CDP.
19. Como Renan, quero que um formulário com pergunta desconhecida fique aberto e estacionado, para não perder o preenchimento.
20. Como Renan, quero continuar na próxima vaga enquanto um formulário espera resposta, para aumentar a chance de bater a meta.
21. Como Renan, quero no máximo um formulário estacionado por vez, para limitar complexidade e uso de memória.
22. Como Renan, quero que as perguntas pendentes sejam expostas em JSON, para que o Hermes possa encaminhá-las sem mover o fluxo inteiro para o Telegram.
23. Como Renan, quero uma CLI de resposta que grave as respostas e retome o formulário, para que a integração com o Hermes seja uma única chamada.
24. Como Renan, quero que o novo sistema rode em paralelo e isolado, para validar o fluxo sem alterar o Hermes, o cron ou o career-ops atual.
25. Como Renan, quero um comando help humano e em JSON, para que o Hermes descubra como usar a CLI sem engenharia reversa.
26. Como Renan, quero screenshots ao abrir a vaga, em cada página do formulário, na revisão, no envio e em erros, para verificar visualmente cada etapa.
27. Como Renan, quero uma captura via `grim` quando o CDP travar, para diagnosticar renderer congelado.
28. Como Renan, quero MP4 opcional por sessão, para auditar o fluxo quando os prints não forem suficientes.
29. Como Renan, quero manter as três últimas sessões completas, para comparar rodadas recentes sem consumir disco indefinidamente.
30. Como Renan, quero um relatório HTML com thumbnails e status por vaga, para revisar a rodada rapidamente.
31. Como Renan, quero um resumo Telegram com o funil completo e o caminho dos artefatos, para saber onde a rodada parou.
32. Como Renan, quero que cada falha tenha motivo explícito e screenshot associado, para não precisar adivinhar o problema.
33. Como Renan, quero um lock de execução, para impedir duas rodadas simultâneas no mesmo navegador.
34. Como Renan, quero retomar uma rodada interrompida sem reaplicar vagas já confirmadas, para que falhas não destruam o progresso do dia.
35. Como Renan, quero um modo dry-run e um modo de uma vaga, para validar mudanças antes de rodar as 20.
36. Como Renan, quero que o limite diário do LinkedIn interrompa a rodada e seja reportado, para evitar insistência em cenário de bloqueio.
37. Como Renan, quero um orçamento máximo de tempo por rodada, para evitar que uma vaga problemática consuma o dia.
38. Como Renan, quero que cada vaga tenha no máximo duas tentativas, para não entrar em loop infinito.
39. Como Renan, quero que o código local seja versionado e testado, para poder revisar, reverter e evoluir com segurança.
40. Como Renan, quero que os scripts necessários sejam copiados para o novo repo sem alterar `~/.local/bin`, para que o cron atual continue intocado.
41. Como Renan, quero que o sistema atual permaneça intocado, para poder comparar as duas abordagens e reverter sem esforço.
42. Como Renan, quero que a sessão diária seja identificável por uma data/run ID, para que prints, logs e relatórios de retomadas pertençam à mesma sessão.
43. Como operador do Hermes, quero que o help liste comandos, argumentos, exit codes e schema JSON, para integrar a CLI sem engenharia reversa.

## Implementation Decisions

- O novo sistema será paralelo e isolado. O Hermes, o cron, a allowlist, `~/.local/bin` e o checkout atual do `career-ops` não serão alterados. Leitura do sistema atual é permitida; escrita não.
- O coração do sistema será uma CLI determinística, com comandos `career-ops-run`, `career-ops-reply`, `career-ops-status`, `career-ops-report` e `career-ops-help`.
- `career-ops-run` recebe uma meta de candidaturas e retorna JSON estruturado com `status`, `submitted`, `target`, `waiting`, `run_id`, `report` e artefatos.
- `career-ops-help --json` publicará um catálogo legível por máquina com comandos, argumentos, exit codes, formato de saída e exemplos. Todo comando também aceitará `--help` em texto humano.
- `career-ops-reply` recebe run, job e respostas; valida, grava no arquivo de respostas, retoma o formulário e devolve o resultado em JSON.
- O loop será por vaga, com fila lazy. A descoberta será acionada apenas quando a fila estiver baixa.
- O estado da vaga seguirá uma máquina explícita: `new`, `title_rejected`, `jd_fetched`, `ineligible`, `eligible`, `cv_ready`, `applying`, `waiting_input`, `submitted`, `verified`, `failed`.
- A confirmação de envio será feita pelo estado do LinkedIn, não apenas pelo código de saída do `easyapply`.
- Cada vaga terá um perfil estruturado com idioma, família, senioridade, skills obrigatórias, skills preferidas e elegibilidade.
- A elegibilidade será determinística, com regras configuráveis e motivos de descarte padronizados.
- O cache de CV será indexado por fingerprint de competências, com gates de idioma, família, senioridade e ausência de must-have faltando.
- O threshold padrão de reuso será 0.90, configurável.
- O CV não incluirá nome de empresa; a empresa ficará na cover letter.
- A geração de CV em cache miss usará o `openai-tailor` existente atrás de um adaptador, com um relatório mínimo montado a partir do perfil estruturado da vaga.
- O `openai-tailor` será chamado apenas em cache miss; o loop de candidaturas não dependerá de LLM.
- O adaptador de aplicação terá uma interface estreita para abrir vaga, aplicar, retomar, verificar e capturar tela.
- A implementação real do adaptador embrulhará `easyapply`, `cdp`, `jobinfo` e as rotinas de CV já existentes.
- O adaptador fake será usado nos testes para simular sucesso, exit 6, CV errado, renderer travado, vaga fechada e limite diário.
- O rastreamento será por run diário, com `events.jsonl`, screenshots e resultado por vaga.
- Screenshots serão capturados em transições nomeadas: vaga aberta, páginas do formulário, seleção de CV, revisão, envio, espera e erro.
- Em timeout de CDP, o sistema tentará uma captura de tela do sistema com `grim` antes de marcar a vaga como falha.
- Vídeo será opcional e desligado por padrão; quando ligado, será um MP4 por sessão.
- A retenção padrão será de três sessões completas, com limpeza automática das mais antigas.
- O relatório será gerado em Markdown e HTML, com thumbnails e links para os artefatos.
- O resumo será texto curto e JSON com funil, status, motivos de bloqueio e caminho da sessão, pronto para o Hermes consumir.
- Integração com Hermes, Telegram, allowlist e cutover do cron ficam fora deste escopo e são responsabilidade do usuário.
- A rodada terá lock de execução e retomada idempotente.
- O limite de tempo, o número máximo de tentativas por vaga e o limite diário do LinkedIn serão configuráveis.
- Os scripts necessários serão copiados para um repositório próprio, com dados e outputs isolados. `~/.local/bin` não será alterado e não haverá symlinks.
- O checkout upstream do `career-ops` não será alterado; ele será usado como dependência de leitura para CV, JD e dados, com outputs no workspace novo.

## Testing Decisions

- Um bom teste verifica comportamento externo observável: resultado da CLI, estado do run, artefatos gerados e chamadas ao adaptador fake. Não deve testar detalhes internos de implementação.
- O seam principal será a CLI. Os testes de aceitação executarão `career-ops-run` e `career-ops-reply` contra um workspace temporário, com adaptador fake e relógio controlado.
- O seam de baixo nível será o adaptador de aplicação. Os testes verificarão o contrato: abrir, aplicar, retomar, verificar e capturar tela.
- O adaptador real será validado por smoke tests manuais e por um teste de uma vaga em ambiente real; não será usado LinkedIn real na suíte automatizada.
- A máquina de estados, elegibilidade, perfil da vaga e cache de CV serão testados através da CLI com fixtures de JD e perfis.
- O cache será testado com casos de hit exato, hit por alta similaridade, must-have faltando, idioma diferente, senioridade incompatível e match abaixo de 0.90.
- A retenção de três sessões será testada criando runs antigos e verificando o que sobra após a limpeza.
- O fluxo de exit 6 será testado com um adaptador fake que devolve `waiting_input`, garantindo que o loop continua, que no máximo um formulário fica estacionado e que `career-ops-reply` retoma.
- O limite de 20 será testado com um adaptador fake que sempre confirma envio; o teste deve provar que o loop para exatamente em 20 e não faz uma 21ª tentativa.
- O caso de CV errado será testado para garantir que a vaga falha e nunca é contada como enviada.
- O caso de renderer travado será testado com timeout do adaptador e verificação de que o artefato de erro e a captura de sistema são registrados.
- O relatório e o `events.jsonl` terão testes de schema e conteúdo, não de formatação visual.
- A CLI terá testes de argumentos inválidos, meta inválida, run inexistente e respostas inválidas.
- O help terá testes de texto humano, catálogo JSON, exit codes, exemplos e cobertura de todos os comandos registrados.
- O isolamento terá testes garantindo que a execução não escreve em `~/.hermes`, `~/.local/bin` ou no checkout atual do `career-ops`.
- O dry-run e o modo de uma vaga terão testes próprios para permitir validação segura.
- O projeto usará `pytest`, que já está disponível no ambiente. O repo upstream do career-ops usa `node:test` em `tests/*.test.mjs`; os testes novos seguirão o mesmo princípio de comportamento externo e fixtures pequenas.
- Cada PR deve incluir teste antes ou junto da mudança e passar a suíte inteira.

## Out of Scope

- Desacoplar completamente o sistema do Hermes.
- Alterar o Hermes, cron, allowlist ou o job atual.
- Fazer cutover, desabilitar o job antigo ou configurar o Telegram.
- Alterar `~/.local/bin` ou o checkout atual do `career-ops`.
- Criar um bot dedicado de respostas no Telegram.
- Reescrever o `easyapply` inteiro.
- Adicionar novas fontes de vagas além do LinkedIn.
- Automatizar login, CAPTCHA ou contornar limites do LinkedIn.
- Gravar vídeo em todas as rodadas por padrão.
- Redesenhar o visual do CV.
- Fazer follow-up automático de candidaturas ou entrevistas.
- Suporte multi-usuário.
- Dashboard em tempo real com servidor.
- Trocar o `openai-tailor` por um modelo local.
- Migrar os dados históricos para outro formato.

## Further Notes

- A rodada de 19/10 teve 1.950 cards, 344 vagas únicas, 129 shortlist, 12 JDs lidas, 4 elegíveis e 0 envios por congelamento no upload de CV. Esse é o caso de referência para observabilidade e confiabilidade.
- O gargalo atual não é falta de vagas; é tempo por candidatura e falhas de UI.
- O cache de CV precisa ser conservador: na dúvida, gerar novo.
- O nome da empresa não pode entrar no CV se o CV for reutilizável.
- O `openai-tailor` será uma dependência do checkout upstream; o adaptador isola a CLI dele.
- O sistema atual não será desabilitado nem alterado. A integração com Hermes/cron fica como handoff para o usuário.
- O help em JSON é o contrato de descoberta para o Hermes: comandos, argumentos, exit codes, exemplos e schema de saída.
- O novo repositório será `/home/gremlin/code/hackajob`, conforme escolhido.
- Esta spec está publicada em `.scratch/career-automation-mvp/spec.md` com `Status: ready-for-agent`.
