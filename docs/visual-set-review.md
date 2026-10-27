> Estado atual: a seção final "Paginação" substitui o limite histórico de 100
> candidatos: padrão/teto total 1.000; página padrão 25 (máximo 100).

# Fila privada de candidatos JPEG — incremento 2026-10-26

## Auditoria e escopo

Base: `feat/visual-pair-review`, `1d42ffeacd1a62cc9f5df82f52cd99bf4c2caa0c`.
Main remota: `96b2144`. Checkout isolado e limpo no Work; nenhum AGENTS.md encontrado.
Sem acesso ao Arch, corpus, backups ou Photo Manager. Sem merge, PR ou alteração de thresholds.

| Capacidade | Estado observado |
| --- | --- |
| Inventário JPEG, SHA-256, pHash, SSIM/MAE, scan e JSON/CSV/HTML | Implementados e cobertos por testes sintéticos |
| Scan histórico com quatro rotações e rótulo `similar_image` | Implementado; rótulo heurístico não confirma identidade |
| Comparação explícita e avaliação persistida | Homologação delimitada no Arch informada pelo operador, conforme handoff |
| Quarentena/restauração exata | Homologação delimitada no Arch informada pelo operador |
| ORB/geometria | Experimental em branches separadas; falsos positivos comprovados; não incorporado |
| Fila de conjunto desta entrega | Testes sintéticos no Work; homologação no Arch pendente |

O retorno da auditoria do Photo Manager não foi disponibilizado nesta sessão. A vinculação
concreta a Assets/localizações e sua estratégia de invalidação são dependências da integração,
não decisões inferidas pelo Lab. Nenhum estudo do dupeGuru foi repetido.

## Contrato

`visual-set` enumera recursivamente jpg/jpeg sem seguir links, valida JPEGs e seleciona pares
com pHash de distância <=8, somente orientação EXIF normalizada, excluindo SHA-256 iguais.
Reutiliza hashing/inventário/prévias existentes; não muda o scan histórico. O helper pHash ainda
calcula quatro hashes internamente, mas somente o primeiro participa desta seleção.
Os pares são ordenados por distância e ID; não formam grupos transitivos. Todas as localizações
são mantidas, inclusive quando várias cópias exatas produzem candidatos com um terceiro arquivo.
Não escolhe representante nem exemplar a preservar.

Limites configuráveis até 200 arquivos elegíveis (inclusive inválidos) e 100 candidatos.
Excesso aborta antes de publicar, sem truncamento. Máximo 19.900 comparações de distância;
SHA-256 lê todos os JPEGs válidos para vincular evidência, diferentemente do scan exato otimizado.
SSIM/MAE só são calculados no par escolhido. Custo também depende de bytes e pixels: não há
quota de tempo/bytes, índice perceptual ou execução adequada a acervos grandes nesta fatia.
Pillow mantém suas proteções padrão; use conjuntos pequenos confiáveis e feche escritores.

`queue.json` contém raiz, paths relativos, identidades de filesystem, SHA-256, dimensões,
exclusões, parâmetros, timestamp UTC e checksum da fila. HTML autocontido mostra IDs, pHash,
prévias e dimensões. JSON e HTML são privados. O checksum detecta alterações acidentais;
não autentica artefatos externos. Consumir somente saídas locais confiáveis do programa.

`visual-set-pair` encontra um ID, verifica ambos os membros por identidade e SHA-256 antes e
ao final da comparação, e persiste avaliação com `provenance.queue_id` e `pair_id`. Arquivo
alterado, removido ou substituído bloqueia publicação; gere nova fila e reavalie. Alterações de
metadados também bloqueiam conservadoramente. Novas entradas no conjunto não são descobertas
implicitamente; a fila é snapshot. Outros pares não são revalidados ao avaliar um par.
Nenhuma decisão anterior é carregada automaticamente numa nova fila.

As saídas devem ser novas, fora do conjunto, sem ancestrais symlink. Não sobrescrevem revisões.
Cada avaliação é um novo artefato; não existe edição/reconciliação automática de decisões.
Uma falha de escrita pode deixar pasta parcial: preserve-a e use outra saída.
Não há transação contra escritores concorrentes/adversariais. A galeria aberta não revalida
arquivos; o comando de avaliação revalida. Uma avaliação persistida também é histórica: antes
de uso futuro no produto, confrontar novamente hashes/localizações atuais.

Aceite humano significa candidato aceito, sem comprovar captura/derivação, preferência ou
qualidade. Nenhum artefato autoriza movimentação ou é consumido pelo executor exato.
Rotação, recorte, edição, sequências, outros formatos e ORB permanecem fora do incremento.
Ausência de candidatos não prova ausência de imagens relacionadas.

## Homologação no Arch pelo operador

Usar worktree isolada da branch `feat/visual-set-review`; preservar alterações locais.

```bash
uv sync --locked
uv run pytest
uv run ruff check .
uv run duplicate-lab visual-set /conjunto-de-estudo \
  --output-dir /revisoes/fila-nova
xdg-open /revisoes/fila-nova/gallery.html
uv run duplicate-lab visual-set-pair /revisoes/fila-nova/queue.json pair-000-001 \
  --output-dir /revisoes/avaliacao-nova \
  --decision accepted_candidate --reason 'Motivo conferido pelo operador'
```

Substituir caminhos e ID pelos valores reais da fila. Usar somente cópias de estudo.
Conferir: par multi-resolução conhecido encontrado; pares exatos ausentes; dimensões/prévias
corretas; avaliação com motivo e proveniência persistidos; nenhuma alteração nas entradas.
Registrar também rejeição ou dúvida quando aplicável. Em cópia sintética separada, mudar um
membro após a descoberta e verificar código 2 sem publicação da avaliação. Conferir limites
com conjunto pequeno e `--max-files 1`. Não publicar artefatos, fotografias ou paths pessoais.
Não há alegação de acurácia geral, nem necessidade de novos algoritmos para este fluxo.

## Validação Work

CPython 3.13.16, dependências do lockfile: `uv sync --locked`, **144 testes aprovados**,
Ruff e `git diff --check` aprovados. O baseline tinha 136 testes.
Casos novos: roundtrip CLI, conteúdo sintético redimensionado versus ruído, exclusão binária,
proveniência/motivo, ausência de mutação, metadados/remoção/symlink, limites sem publicação,
exclusões/resultado vazio, checksum/ID, mutação durante renderização e saída fora do conjunto.
Não houve inspeção visual em navegador no Work nem teste com fotografias do operador.

## Homologação Arch informada pelo operador — 2026-10-27

Commit testado: 87ab7d4. Operador reportou 144 testes e Ruff aprovados.

- Subconjunto de dez JPEGs: 45 candidatos descobertos.
- Galeria aberta, com prévias, IDs, nomes e dimensões visíveis.
- Par em duas resoluções comparado e aceito pelo operador; avaliação
  persistida com vínculo à fila e ao par, sem autorização de ação.
- Teste sintético posterior: alteração de membro bloqueou a avaliação,
  sem publicar revisão inválida.

O conjunto completo excedeu o limite de 100 candidatos e foi bloqueado.
Sua revisão integral não está homologada. A quantidade de pares permanece
uma limitação de usabilidade a diagnosticar, sem elevar limites ou alterar
thresholds automaticamente.

Evidências fornecidas pelo operador; o Work não inspecionou diretamente
os artefatos do Arch. Não demonstram acurácia geral do detector.

## Continuidade: candidatos por conteúdo binário (opt-in)

Branch `feat/visual-content-candidates`, base publicada `31aa8cc`.
A enumeração anterior repetia comparações entre conteúdos quando havia cópias exatas em
várias localizações. Por exemplo, 11 cópias de A e 11 de B geram 121 pares de caminhos,
mas somente uma comparação entre dois conteúdos binários distintos. Isso explica uma fonte
possível de multiplicação; não estabelece a causa nem a contagem do conjunto real do operador.

O modo opcional `--collapse-exact` reúne apenas SHA-256 iguais antes da seleção perceptual.
Cada candidato contém `left_members`/`right_members` com todos os índices em `files`, sem
perder localizações. Representantes são os primeiros caminhos na ordenação lexical, sem
preferência de qualidade/preservação. A galeria exibe as listas completas em blocos expansíveis.
Não agrupa por pHash, similaridade transitiva, captura ou derivação. Dez conteúdos distintos
continuam com até 45 pares; não se substitui esse grafo por nove avaliações presumidas.

O modo novo produz `visual-set-review` **v2**. O leitor atual aceita v1 e v2; o leitor antigo
rejeita v2, evitando interpretar membros agrupados como pares simples. Fila antiga e suas
avaliações permanecem intactas. O modo sem a opção mantém v1 e comportamento por caminhos.
Não há migração automática, propagação de aceite ou importação de avaliações históricas.

A avaliação v2 ainda compara somente os dois representantes. Sua proveniência registra
`assessment_scope=displayed_representatives_only` e todas as localizações observadas.
Todos os membros dos dois lados são revalidados por identidade e SHA-256 antes e ao final
da comparação, inclusive os não exibidos. Alteração/remoção/link bloqueia sem substituir
automaticamente representante. Não autoriza ações, nem altera Assets ou preferências.

Os limites permanecem 200 arquivos/100 candidatos. O limite de 100 é aplicado após reunir
cópias exatas quando a opção está ativa. O código conta todos os pares dentro do limite de
arquivos (até 19.900); se exceder candidatos, informa totais e não publica saída.
O resumo JSON/terminal distingue arquivos, conteúdos únicos, pares de localizações,
candidatos revisáveis e repetições reunidas. Em v1 as repetições reunidas são zero.
Custo de inventário, SHA-256, pHash e prévias por arquivo permanece; não é índice para acervos
grandes nem melhora de acurácia. Limiar 8, EXIF e ausência de busca de rotação não mudaram.

### Homologação proposta no Arch

Usar branch nova em worktree isolada e saída privada nova. Preservar revisões anteriores.
Não há `set -e` nem limpeza automática de arquivos do operador neste roteiro.

```bash
uv sync --locked
uv run pytest
uv run ruff check .
uv run duplicate-lab visual-set /conjunto-de-estudo \
  --collapse-exact --output-dir /revisoes/fila-por-conteudo-nova
```

Substituir os dois caminhos antes de executar. Enviar somente o resumo numérico, sem JSON
operacional, caminhos privados ou fotografias. Se exceder 100, registrar a mensagem: não
ampliar limites. Se publicar, abrir galeria, conferir listas de localizações, escolher um ID
e usar `visual-set-pair` em saída nova. A avaliação permanece restrita aos representantes.
A comparação com a fila anterior é diagnóstica; não herdar aceite por conteúdo automaticamente.

### Validação Work

151 testes e Ruff aprovados; `git diff --check` aprovado. Evidências sintéticas novas:
22 localizações/2 conteúdos produzem 121 pares no modo antigo (bloqueado) e um candidato no
modo novo; quatro localizações mantidas numa avaliação com escopo explícito; alteração,
remoção e symlink em membro não representante bloqueados; mutação durante prévia bloqueada;
dez conteúdos distintos mantêm 45 candidatos mesmo com pHash igual; roundtrip CLI v2 e
compatibilidade dos testes v1. Sem acesso ao corpus ou homologação Arch desta extensão.

## Paginação — continuidade de 2026-10-27

Base de implementação `6c2dd3a`, branch nova `feat/visual-queue-pagination`.
Operador reportou no Arch: 151 testes e Ruff aprovados; com `--collapse-exact`, o conjunto
completo encontrou **156 revisões e 156 pares de localizações**, excedendo 100 e sem publicar
fila. Portanto, reunir cópias binárias não reduziu candidatos nesse conjunto. A hipótese de
multiplicação por cópias não explica esse resultado; não há diagnóstico de acurácia geral.
Os 151 testes validam a extensão, não sua utilidade quantitativa no conjunto real.

### Contrato atual

- Descoberta mantém pHash <=8, sem busca de rotações, no máximo 200 arquivos, até 19.900
  comparações de distância. Sem novos algoritmos, alteração de thresholds ou transitividade.
- `--max-candidates` agora tem padrão **1.000** e teto 1.000. Esse é aumento explícito e
  limitado do orçamento de materialização da fila, motivado pelo caso de 156 candidatos.
  Não modifica o teto de arquivos/comparações, nem calcula SSIM/MAE durante a descoberta.
  Acima desse orçamento, o comando informa o total e aborta antes de publicar; não trunca.
  Quem deseja manter o bloqueio antigo pode usar `--max-candidates 100`.
- `--page-size` padrão **25**, intervalo 1..100, limita candidatos por arquivo HTML,
  independentemente do limite total. Fila completa permanece em `queue.json` v1/v2.
  ID de par, ordem por pHash/ID e referência ao conteúdo não dependem da página.
- `gallery.html` é a primeira página; seguintes são `page-0002.html`, etc. Links relativos
  Anterior/Próxima, primeira/última e páginas vizinhas funcionam localmente, sem JavaScript
  ou rede. Cada página informa número, total de páginas/candidatos e ID da fila.
- `gallery-index.json` v1, com checksum e `queue_id`, mapeia páginas para IDs de pares.
  Não é autorização nem um novo contrato de revisão. Nenhum candidato é descartado ou
  aparece em duas páginas; conjunto vazio gera uma página sem pares.
- Avaliação continua via `visual-set-pair queue.json ID`, independentemente da página.
  Navegar não grava aceite nem progresso. Não há agregação automática das avaliações,
  fila de pendências dinâmica ou propagação de decisões. Relatórios antigos ficam intactos.
- Cada HTML inclui suas prévias, mas a galeria completa é agora um diretório: preservar
  todos os HTMLs, índice e fila ao transferir/arquivar. HTML isolado não contém outras páginas.
- A geração ainda mantém candidatos/prévias/HTMLs em memória, revalida arquivos antes de
  publicar e pode deixar pasta parcial em falha de escrita. Não é streaming nem promessa
  de limite rígido de memória/bytes/tempo. Paginar melhora navegação, não reduz 156 avaliações.

### Homologação Arch proposta

Depois de importar a branch em worktree nova e rodar testes/Ruff, criar saída nova e usar
as cópias de estudo. Exemplo com placeholders (substituir antes de executar):

```bash
uv run duplicate-lab visual-set /conjunto-de-estudo \
  --collapse-exact --page-size 25 --output-dir /revisoes/fila-paginada-nova
xdg-open /revisoes/fila-paginada-nova/gallery.html
```

Se entradas e seleção permanecerem iguais, esperar 156 candidatos, sete páginas, 25 pares
nas seis primeiras e seis na última. Isso é expectativa, não resultado já obtido.
Conferir links Próxima/Anterior, acesso à última página, listas de localizações e vínculo
à fila. Escolher ID na última página, gerar comparação pendente em saída nova e conferir
proveniência. Não assumir aceite do conteúdo ao testar navegação. Não publicar artefatos.
Verificar, pelo índice, contagem completa e ausência de IDs repetidos. Se o conjunto mudou,
registrar nova contagem sem forçar a expectativa histórica.

### Validação Work desta fatia

159 testes, Ruff e `git diff --check` aprovados. Novos casos sintéticos: fila com 171 pares
em sete páginas nos modos v1/v2, cobertura integral e única por ID, todos os links apontando
para HTMLs gerados, última página parcial, avaliação de par da última página via CLI com
proveniência mantida, fila vazia, tamanho de página independente e argumentos inválidos.
1.035 candidatos excedem o teto total de 1.000 e impedem publicação mesmo com páginas de 25.
Testes de invalidação e compatibilidade anteriores continuam aprovados.
Não houve inspeção em navegador no Work ou acesso ao Arch/corpus; homologação desta paginação
pendente. A integração ao Photo Manager continua independente e não foi modificada.

## Homologação da paginação no Arch — 2026-10-27

Evidências informadas pelo operador no commit a9038f2:

- 159 testes e Ruff aprovados.
- Conjunto com 61 JPEGs e 52 conteúdos binários distintos.
- Fila gerada com 156 candidatos; agrupamento binário não reduziu os pares.
- Navegação entre páginas confirmada pelo operador.
- Índice conferido: cobertura integral, sem IDs repetidos.
- Distribuição: seis páginas com 25 pares e última com seis.
- Comparação de um ID da última página gerada com proveniência da fila,
  escopo restrito aos representantes, decisão pending e ação não autorizada.

Isso valida descoberta, paginação e acesso à comparação por ID neste
conjunto. Não demonstra acurácia geral, aceite humano desse último par
ou revisão individual dos 156 candidatos.
Artefatos operacionais e fotografias permanecem privados.
