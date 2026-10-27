# Checkpoint de convergência: Duplicate Lab → Photo Manager

Histórico iniciado em 2026-10-24; consolidado em 2026-10-26.
Este documento prepara a integração; não registra implementação no Photo Manager.

## Estado atual consolidado — 2026-10-26

Este documento mantém abaixo o histórico das entregas. Pendências e números das seções
anteriores descrevem aquele momento; para o estado atual, prevalece este resumo.

- Entrega visual publicada em `feat/visual-pair-review`, commit `16f61d96ccea2ab191bf7631c0270c36fa48bee3`.
- Work: 136 testes, Ruff e verificação do diff aprovados. Arch: operador informou
  136 testes e Ruff aprovados.
- Quarentena/restauração de exatas homologada nas cópias de estudo: nove candidatos
  movidos e restaurados, preservado mantido, journal registrado (detalhes abaixo).
- Revisão de pares: HTML aberto e conteúdo avaliado pelo operador; aceite e rejeição
  persistidos por CLI, conforme saídas enviadas. Nenhuma movimentação por similaridade.
- Sem alteração do Photo Manager, merge ou PR nesta entrega.

### Evidências visuais fornecidas pelo operador

| Caso de estudo | Resultado | Avaliação humana registrada |
| --- | --- | --- |
| Mesmo quadro em 1920 × 1080 e 3840 × 2160 | SHA-256 distintos; pHash 0; SSIM 0,999310; MAE 0,001091 | `accepted_candidate`: mesmo conteúdo visual/enquadramento em resoluções diferentes |
| Foto individual versus composição que repete essa foto | SHA-256 distintos; pHash 24; SSIM 0,104538; MAE 0,284643 | `rejected_candidate` para equivalência de redimensionamento/recompressão; conteúdo relacionado |

O segundo caso não é um negativo de conteúdo totalmente independente: é um derivado relacionado,
com estrutura global diferente. A relação foi descrita pelo operador, não inferida pelo detector.
Derivação, equivalência visual, igualdade binária e identidade de captura devem permanecer
conceitos separados. Maior resolução não comprova maior qualidade ou originalidade histórica.

A homologação demonstra o fluxo mínimo de comparação e registro humano em dois pares, não
acurácia, cobertura de recompressão isolada ou classificação automática de transformações.
As métricas usam quadro normalizado em cinza a 512 × 512; prévias reduzidas não certificam
detalhe integral. O Work não leu diretamente os artefatos ou fotografias do Arch.
Arquivos, hashes individuais, nomes e caminhos privados não são publicados neste checkpoint.

### Próxima fatia no Photo Manager

1. Auditar o estado real do produto e seus contratos antes de incorporar código; nenhuma
   alteração no outro repositório está autorizada por este checkpoint.
2. Priorizar grupos binários exatos sobre localizações catalogadas, com todos os caminhos,
   escolha/motivo e protegidos visíveis, sem fundir Assets ou perder anotações.
3. Demonstrar primeiro o plano revisável sem mutação; depois integrar quarentena somente com
   coordenação explícita entre journal, localizações e recuperação do catálogo.
4. Manter revisão visual como avaliação humana separada, vinculada aos hashes/localizações
   observados, com invalidação quando o conteúdo mudar. Não consumir seu JSON como plano
   de execução nem habilitar movimentação por similaridade.
5. Reaproveitar capacidades como módulo interno do produto único. Não criar serviço separado,
   nova interface definitiva no Lab, novos algoritmos ou retomar ORB/Fase 05C nesta passagem.

Critério do checkpoint: exatas e revisão humana delimitadas têm evidências suficientes para
iniciar avaliação de incorporação no produto; integração e merge continuam pendentes.

## Fonte e estado histórico

- Repositório: `CleberNandi/playmemory-duplicate-lab`.
- Branch de entrega: `feat/exact-duplicate-review-plan`.
- Main de origem verificada: `96b214475dc56fa4e828f9c0bf9eb3b3b6db3a3f` (0.2.2).
- `c36448cf425779ef2ff514bfb4219d0069da9574`: snapshot, plano e revalidação.
- `7afaadd33a147b57d8909f128ed8ea1508402ed8`: galeria offline do plano.
- A revisão atual acrescenta rótulos em português e este checkpoint. Usar a versão
  integral da branch, inspecionando seu HEAD antes de qualquer incorporação.
- Não houve merge na main, PR, alteração das branches ORB ou acesso à workstation pelo Work.

## O que está disponível

| Capacidade | Implementação | Limite |
| --- | --- | --- |
| Grupos binários exatos | `hashing.find_exact_groups` | Tamanho + SHA-256; não escolhe caminho nem identidade de captura |
| Snapshot persistido | `exact_plan.exact_scan` | Extensões configuradas; bytes elegíveis não certificam imagem válida |
| Preferência operacional | `retention.build_retention_report` | Regra externa ou decisão humana; proteção aplicada pelo adaptador do plano |
| Plano e revalidação | `exact_plan.build_plan` / `revalidate_plan` | Sem autorização de execução; checksum não autentica artefato |
| Revisão visual | `html_report.write_exact_gallery` / CLI `exact-gallery` | HTML estático e privado, miniaturas; sem edição de escolhas |

Contratos e limites completos: [plano exato](exact-duplicate-review-plan.md).
Estudo oficial e licença: [comparação com dupeGuru](dupeguru-comparison.md).

## Evidências realmente obtidas

- Work: 94 testes sintéticos e Ruff aprovados na implementação da galeria.
- Arch, retorno do operador: 90 testes e Ruff aprovados antes da extensão da galeria.
- Arch: 61 arquivos inventariados, um grupo com 10 cópias idênticas, um caminho escolhido
  e nove candidatos. Plano sem bloqueios e inalterado na revalidação.
- Operador confirmou que todo o material utilizado era cópia de teste, sem originais oficiais.
- Operações executadas=False; movimentação autorizada=False.
- Captura enviada pelo operador comprova abertura do HTML, grupo expandido, miniaturas,
  destaque do preservado e identificação do candidato. Busca e alternância de expansão
  não têm confirmação individual registrada; não são declaradas aprovadas pela captura.
- Os 94 testes ainda não foram reportados no Arch. Não há teste de movimentação/restauração.

Fotografias, captura de tela, nomes reais de arquivos, caminhos privados e JSONs operacionais
permanecem fora deste handoff público. As evidências locais devem ser preservadas pelo operador.

## Próximo incremento proposto no produto principal

Objetivo demonstrável: catalogar cópias de teste → identificar grupos exatos → mostrar todos os
membros/localizações → registrar escolha de preservação → apresentar plano sem executá-lo.

1. Conferir o estado e as decisões atuais do Photo Manager e do laboratório Sony. Este chat
   não inspecionou seus repositórios; não presumir versão, arquitetura de UI ou contratos atuais.
2. Mapear grupo de conteúdo para Asset e suas localizações, respeitando a identidade interna
   do catálogo. Mesmo digest não autoriza colapsar identidades, perder anotações ou apagar paths.
3. Incorporar o mínimo necessário como módulo interno do produto único, após revisão de código
   e contratos. O Lab não precisa virar serviço, API remota ou dependência de runtime independente.
   A forma concreta de migração e o versionamento serão definidos no repositório do produto.
4. Integrar escolhas à interface do Photo Manager. O HTML é referência funcional de revisão,
   não layout definitivo, e não deve determinar a arquitetura da interface.
5. Demonstrar o fluxo com cópias e critérios de aceite observáveis: grupos corretos, todos os
   caminhos visíveis, protegidos fora dos candidatos, escolha/motivo persistidos, arquivos
   alterados bloqueados e nenhuma mutação do acervo.

Antes de consumir os JSONs em uma interface/processo privilegiado, aplicar schema rigoroso,
validação de caminhos e versões, vinculação ao catálogo e limites explícitos de confiança.
O checksum atual serve para integridade acidental; o plano não é um comando autenticado.
Não transportar dependências perceptuais do Lab para o produto sem necessidade demonstrada.

## Pendências deliberadas

- Quarentena, journal durável, retomada, restauração e autorização de ação vinculada ao plano.
- Proteção contra corridas durante ações, destinos exclusivos e protocolo entre filesystems.
- Resolução de dependências de catálogos/sidecars e tratamento operacional de links.
- ORB/similaridade/identidade de captura continuam fora do critério de duplicação exata;
  Fase 05C não executada nem necessária para este checkpoint.

A convergência deve produzir uma fatia utilizável do Photo Manager, com demonstração e critérios
de aceite, antes de ampliar a sequência de estudos ou construir outro produto no Lab.

## Atualização de 2026-10-26 — quarentena exata isolada

Branch `feat/exact-reversible-quarantine`, baseada em `4a93464`. O módulo interno
`duplicate_lab.quarantine` acrescenta autorização vinculada ao plano, journal SQLite,
movimentação Linux sem sobrescrita no mesmo filesystem, retomada e restauração.
Contrato e homologação: [quarentena reversível](exact-reversible-quarantine.md).
A evidência nova é sintética no Work; ainda não há homologação operacional no Arch.
Não houve modificação do Photo Manager, merge, PR ou incorporação de código dupeGuru.

Para incorporar no produto, substituir o reconhecimento manual de dependências por vinculação
explícita às localizações/identidades do catálogo e um protocolo coordenado de atualização e
recuperação. O journal de filesystem não é transação atômica com o banco do catálogo.
Não chamar o executor diretamente enquanto o catálogo observa/escreve os mesmos caminhos.
A UI/CLI experimental do Lab não determina interface definitiva nem serviço separado.

### Próximo incremento visual delimitado

| Caso | Capacidade existente | Falta / continuidade |
| --- | --- | --- |
| Redimensionamento/recompressão | pHash, SSIM, MAE, relatórios e testes de benchmark | Comparação humana de pares com dimensões e indicação de transformação; primeiro incremento |
| Rotação, recorte, edição | Trilha experimental ORB e evidências de falsos positivos | Revisão humana e evidências por transformação; sem nova Fase 05C nem thresholds automáticos |
| Sequências semelhantes | Candidatos perceptuais podem aproximar cenas distintas | Identidade de captura não é demonstrada; manter fotos distintas por padrão |
| Outros formatos/mídias | Scan binário aceita extensões configuradas | Decoder, metadados e comparação visual por formato não estão homologados; vídeo fora do incremento |

Começar somente por pares redimensionados/recomprimidos nos conjuntos de estudo já existentes,
com comparação lado a lado, aceitação/rejeição humana registrada e sem operações de arquivo.
Não inferir mesma captura por geometria consistente. Manter separados: igualdade binária,
similaridade visual, identidade de captura, preferência de preservação e autorização de ação.
O produto final continua sendo o Photo Manager; esta revisão visual é evidência para seu módulo
interno, sem criar outra interface definitiva no laboratório.

## Homologação no Arch informada pelo operador — 2026-10-26

No commit `5a0b12e`, o operador reportou 133 testes e Ruff aprovados, mais o ciclo sintético
com movimentação e restauração verificadas. Em seguida, autorizou uma sessão nova nas cópias
de estudo: um preservado, nove candidatos, nenhuma dependência externa de catálogo.
O executor registrou nove ações `moved`; o operador confirmou visualmente um preservado na
origem e nove candidatos na quarentena. Depois de autorização de restauração, o retorno do
executor registrou nove ações `restored`, com conteúdo verificado e sem sobrescrita.
Essas evidências foram fornecidas pelo operador; o Work não inspecionou a workstation ou seu
journal diretamente. A confirmação visual individual após restauração não foi registrada.

Este resultado substitui a pendência de homologação operacional indicada na atualização anterior.
Não amplia autorização a originais ou outras sessões. Plano, autorização e journal continuam
privados com o operador; nova movimentação exige scan/plano/autorização novos.

O incremento seguinte é [revisão explícita de par visual](visual-pair-review.md), com métricas,
prévias e avaliação humana persistida, sem identidade de captura presumida ou ação por similaridade.

## Continuidade — fila visual de conjunto (2026-10-26)

Branch `feat/visual-set-review`, baseada no checkpoint `1d42ffe`. Contrato, auditoria de
capacidades e roteiro Arch: [fila de revisão](visual-set-review.md).
Descoberta JPEG limitada reutiliza pHash existente, sem busca de rotações ou novos thresholds,
e separa pares SHA-256 iguais. Galeria privada permite escolher ID; comparação humana existente
persiste avaliação ligada à fila/par e bloqueia conteúdo/identidade alterados.
Não gera autorização, preferência, fusão de Assets ou operação no acervo.

Retorno da auditoria do Photo Manager ausente nesta sessão: integrar ao catálogo somente após
mapear localizações/hashes e invalidação no produto. A CLI/HTML é contrato experimental,
não segunda interface definitiva. Evidência nova somente sintética no Work; Arch pendente.

### Extensão opcional: candidatos por conteúdo binário

Branch `feat/visual-content-candidates`, derivada de `31aa8cc`: modo opt-in reúne somente
localizações com SHA-256 igual para evitar repetir uma comparação visual por cada cópia.
Fila v2 preserva todos os membros, revalida ambos os lados e mantém avaliação restrita aos
representantes exibidos. Leitor novo aceita v1/v2; leitor antigo rejeita v2.
Não agrupa conteúdos perceptualmente similares ou presume relações transitivas. Limites e
threshold permanecem. Diagnóstico do conjunto completo e homologação Arch ainda pendentes;
nenhuma modificação no Photo Manager. Ver contrato em `visual-set-review.md`.

### Fila paginada — extensão do contrato de apresentação

Na continuidade após `6c2dd3a`, operador reportou 151 testes/Ruff aprovados no Arch e
156 candidatos/156 pares de localizações: agrupar cópias SHA-256 não reduziu o conjunto.
Branch `feat/visual-queue-pagination` separa orçamento total (padrão/teto 1.000 candidatos)
de tamanho da página (padrão 25, máximo 100), mantendo 200 arquivos e seleção existente.
Fila integral v1/v2 e IDs preservados; índice vincula páginas e pares, sem descartar pares,
propagar avaliações ou autorizar operações. Galeria local passa a ocupar vários HTMLs.
159 testes sintéticos/Ruff aprovados no Work; paginação no Arch pendente. O aumento limitado
de orçamento é explícito, não melhoria de acurácia ou redução de avaliações.
Não altera o Photo Manager nem exige sua interface adotar a galeria do Lab.
