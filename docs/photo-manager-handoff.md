# Checkpoint de convergência: Duplicate Lab → Photo Manager

Data: 2026-10-24. Entrega limitada a leitura, revisão e plano de duplicatas binárias.
Este documento prepara a integração; não registra implementação no Photo Manager.

## Fonte e estado

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
