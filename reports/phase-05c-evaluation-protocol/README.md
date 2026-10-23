# Fase 05C — Protocolo de avaliação de identidade e correspondência parcial

Data: 2026-10-23. Revisão: 1. Estado: protocolo preparado; execução não iniciada.

## Objetivo e escopo

Avaliar se a evidência local permite distinguir derivados da mesma captura de
correspondência parcial entre imagens. A saída continua sendo evidência para
revisão humana; nenhuma classificação autoriza retenção, movimentação ou exclusão.

Este commit documenta o desenho experimental. Não adiciona implementação,
thresholds, dependências, execução de benchmark ou alterações de produção.
A Fase 05B permanece encerrada em seu commit próprio:
`7e0fd26bd2220cdf2eb7f6cb2fae6ad483dfb460`.

Baseline de produção: `96b214475dc56fa4e828f9c0bf9eb3b3b6db3a3f`.
Baseline experimental: `b9bf4a10bbef4aac14a5945ce9bd0f7dfeecb627`.
Consultar também [o encerramento da 05B](../phase-05b-orb-false-positives/closure.md).

## Contrato de referência

Usar dimensões separadas, evitando tratar semelhança como identidade:

| Dimensão | Valores | Evidência exigida |
|---|---|---|
| Igualdade binária | igual / diferente | SHA-256 dos arquivos disponíveis |
| Relação de captura | mesma / distinta / indeterminada / múltiplas fontes | Proveniência ou referência documentada; ORB não define o rótulo |
| Transformação | intacta / recompressão / resize / recorte / composição / outra | Receita ou anotação verificável; permitir vários valores |
| Conteúdo compartilhado | observado / não observado / indeterminado | Inspeção ou derivação conhecida; ausência de matches não prova ausência |
| Confiança da referência | verificada / referência de dataset / incerta | Fonte e justificativa registradas |

Um recorte derivado de uma única captura é positivo para identidade, mesmo com
baixa cobertura. Uma composição de múltiplas capturas mantém relações com suas
fontes, mas fica fora da classificação binária primária de captura única.
Fotografias distintas do mesmo objeto ou cena são negativas quando a referência
for confiável. Casos indeterminados ficam em estrato próprio, sem rótulo forçado.

Os dois FP da 05B continuam negativos segundo a regra histórica de capture_id
do Copydays. Essa regra não comprova a proveniência física de cada região.
Se novas evidências alterarem a referência, registrar nova versão e reportar
ambas as interpretações; nunca corrigir silenciosamente os resultados anteriores.

## Conjunto e prevenção de vazamento

1. Inventariar somente leitura: caminhos relativos, hashes, dimensões, origem,
   licença, identidade/família de origem e disponibilidade dos arquivos.
2. Separar os casos conhecidos da 05B e todo o benchmark já inspecionado como
   conjunto de desenvolvimento/regressão. Não chamá-los de teste inédito.
3. Reunir positivos verificáveis: recompressão, resize e recortes legítimos,
   incluindo recortes pequenos. Registrar receita e seed de derivados sintéticos;
   gravá-los apenas em diretório novo, sem sobrescrever os originais.
4. Reunir negativos: capturas distintas com cena semelhante, estruturas
   repetitivas, conteúdo parcial compartilhado e distratores comuns. Incluir
   composições como desafio semântico separado.
5. Agrupar por família de origem antes da divisão: original, derivados e
   composições com fontes conhecidas devem permanecer na mesma partição. Para
   composições, usar componentes conectados das relações entre fontes.
6. Separar desenvolvimento, calibração e avaliação final por essas famílias.
   Registrar manifesto, regra de divisão, seed e hashes antes de medir variantes.
   Verificar interseção de famílias e hashes; bloquear execução se houver vazamento.
7. Congelar quantidades por estrato, critérios de inclusão/exclusão e orçamento
   de revisão antes da avaliação final. Essas quantidades dependem do inventário
   real; este documento não inventa tamanho de amostra nem poder estatístico.

Sem famílias novas e referências suficientes, reportar apenas estudo exploratório.
Anotar rótulos antes de consultar decisões do algoritmo sempre que possível;
divergências exigem revisão e justificativa, mantendo o histórico de anotações.

## Comparações planejadas

Primeiro executar o baseline congelado e reproduzir as decisões conhecidas.
Separar duas perguntas: a implementação usa a geometria pretendida? Essa
geometria discrimina identidade de captura? A primeira não resolve a segunda.

| Comparação | Finalidade | Estado |
|---|---|---|
| ORB mutual histórico, geometria direta | Baseline com semântica real documentada | Código congelado; não executado nesta fase |
| RANSAC somente em matches recíprocos | Ablação para isolar a base geométrica | Planejada; diagnóstico prévio não é nova avaliação |
| Diagnósticos de distribuição espacial | Medir concentração e erro por estrato | Análise planejada; nenhum novo corte decisório |

Usar os mesmos pares e partições nas comparações. Distinguir cobertura de todos
os matches, cobertura dos inliers e bounding box de sobreposição real. Registrar
falhas de leitura, ausência de descritores e geometrias inválidas explicitamente.
Não remover casos difíceis ou falhos do denominador sem contabilização.

Nenhum novo algoritmo ou busca de thresholds faz parte deste protocolo inicial.
Se uma mitigação for proposta depois, congelar sua hipótese, espaço de busca,
regra de seleção e tolerância de regressão antes de abrir a avaliação final.
Resultados usados para escolher uma variante passam a ser desenvolvimento.

## Métricas e denominadores

Unidade primária: par consulta–candidato de captura única com referência elegível.
Registrar TP, FP, FN e TN, número de pares elegíveis, excluídos e indeterminados.

- Precisão: TP / (TP + FP); recall: TP / (TP + FN).
- Taxa de FP por par: FP / (FP + TN).
- Taxa por consulta: consultas com ao menos um FP / consultas elegíveis,
  separando consultas com e sem positivo esperado.
- Recall de recortes: TP / positivos de recorte; estratos de transformação
  definidos no manifesto antes da avaliação.
- Casos de composição/ambiguidade: tabela separada de aceitação e justificativa,
  sem misturar com precisão binária primária.

Denominador zero produz resultado não definido, nunca zero artificial.
Reportar contagens e intervalos de incerteza junto das taxas. Pares da mesma
família não são independentes: usar reamostragem por família quando viável;
intervalos binomiais simples serão apenas descritivos, com essa limitação.
Comparações usam diferenças pareadas por família. Não prometer ausência de FP
a partir de zero erros observados em uma amostra pequena.

Avaliar o verificador em uma lista congelada de pares, sem mudar recuperação de
candidatos. Se houver avaliação de ranking depois, distinguir recall de candidatos
de recall de confirmação e registrar tamanho da base por consulta. Precisão
depende da composição/prevalência do benchmark e não estima diretamente uso real.

## Rastreabilidade e privacidade

Cada execução futura deve guardar: SHA de código, configuração completa e hash,
manifesto e hash, versões Python/OpenCV/NumPy/Pillow, sistema/CPU, threads,
seed, comandos, timestamps e erros. Guardar resultados por par e sumário derivado.
O ambiente OpenCV 5.0.0 da 05B é informação reportada, não ambiente reproduzido aqui.

Guardar privadamente os JSONs brutos e visualizações originais da 05B quando
recuperados; verificar seus hashes e correspondência com as métricas consolidadas.
Não reconstruí-los como se fossem os originais. Publicar somente métricas e
documentação revisadas, sem fotos, EXIF sensível ou caminhos pessoais absolutos.

## Gates e decisão

| Gate | Critério | Estado atual |
|---|---|---|
| C0 — desenho | Contrato, limites e métricas documentados | Preparado neste documento |
| C1 — dados | Corpus acessível, proveniência, estratos e partições auditados | Pendente |
| C2 — reprodução | Baseline executado com logs, hashes e divergências registradas | Pendente |
| C3 — comparação | Execuções pareadas, resultados por estrato e incerteza | Pendente |
| C4 — conclusão | Revisão dos erros, limitações e decisão fundamentada | Pendente |

PASS de uma execução significa protocolo cumprido e resultados auditáveis; não
significa que ORB provou identidade. PASS WITH RESERVATIONS exige limitações
explícitas de dados/reprodução. Vazamento, rótulos sem fundamento, resultados
inventados ou alteração silenciosa de configuração invalidam a avaliação (FAIL).

Nenhuma variante pode ser recomendada para produção sem critérios quantitativos
de risco e de recall definidos antes do teste final. Como esses critérios e os
dados ainda não foram congelados, não há gate de promoção aprovado nesta fase.
A próxima ação concreta é inventariar os dados disponíveis na workstation e
recuperar os diagnósticos privados; não executar uma varredura de thresholds.
