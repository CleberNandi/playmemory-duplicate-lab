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
