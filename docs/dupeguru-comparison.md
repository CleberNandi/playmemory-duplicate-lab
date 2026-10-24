# dupeGuru: comparação limitada ao fluxo exato

Inspeção em 2026-10-24, repositório oficial `arsenetar/dupeguru`, commit fixado
[`db097a030150b3d4ea9f492b85e7e4e4bcb3f789`](https://github.com/arsenetar/dupeguru/commit/db097a030150b3d4ea9f492b85e7e4e4bcb3f789).
Não foi instalado, executado ou modificado. **Nenhum comportamento do dupeGuru foi testado
neste ambiente**; a tabela separa documentação e leitura da implementação.
O identificador da ferramenta REA permanece desconhecido e não foi presumido.

| Tema | Documentação oficial no commit | Implementação observada no commit | Decisão para o Lab |
| --- | --- | --- | --- |
| Conteúdo | Standard/Contents usa tamanho e MD5; Picture/Contents é comparação visual | `engine.getmatches_by_contents` agrupa por tamanho, compara hash parcial e completo; `fs.py` prefere xxHash128 e usa MD5 como fallback. Com `bigsize > 0`, a ramificação para arquivos grandes usa amostras em vez do digest completo | Reutilizar detector SHA-256 completo existente; não equiparar todos os modos/configurações |
| Grupos/referências | Um membro de referência não pode ser marcado; promoção manual disponível | Scanner prioriza grupos e elimina grupos só de referência; comparação entre dois membros de pastas Reference é evitada | SHA-256 identifica grupo; escolha de caminho é independente e explícita |
| Pastas Reference | Arquivos não podem ser excluídos; referências adicionais podem desaparecer do grupo exibido | Filtro por `is_ref` na descoberta de correspondências; preferência de referência na ordenação | Mostrar todas as cópias e todos os membros protegidos |
| Marcação/revisão | Marcar é diferente de selecionar; painel Details e revisão manual antes de excluir | Ações passam por `perform_on_marked`; falhas por arquivo vão para `problems` | Aproveitar a revisão existente; não reconstruir UI neste incremento |
| Links | Documentação oferece substituição de removidos por symlinks/hardlinks | `File.can_handle` rejeita symlinks; `ignore_hardlink_matches` é opção, default False. `_remove_hardlink_dupes` deduplica por inode | Excluir/listar symlinks; bloquear grupos com hardlinks, sem substituição por links |
| Mudanças após scan | Documentação de uso não estabelece o protocolo de revalidação exigido pelo Lab | Cache é indexado por path/size/mtime_ns, com opção de ignorar mtime. `include_exists_check` checa existência durante o scan. Nos caminhos de cópia/movimentação/deleção inspecionados não há novo hash completo de origem e referência antes de agir | Revalidar metadados e SHA-256 inclusive do preservado; execução terá contrato próprio |
| Movimentação/conflitos | Move/Copy Marked aceita destino e recriação de caminhos conforme preferência | `copy_or_move` calcula destino; `smart_move` gera nome alternativo para conflito observado e usa `shutil.move` | Plano aponta destino determinístico; conflito bloqueia, sem renomeação automática |
| Recuperação | Send Marked to Trash é documentado; também há exclusão direta nas opções | `send2trash` ou `os.remove`, conforme opção; erros por arquivo registrados. Nos trechos de ação inspecionados não aparece journal durável de movimentação/restauração | Não alegar recuperação transacional no dupeGuru; projetar journal/restauração separadamente |

Ausência observada em trechos específicos não prova ausência em todo o produto. Lixeira do
sistema e resultado salvo não equivalem ao journal de quarentena exigido aqui. O mecanismo de
nomes alternativos observado também não comprova proteção contra corridas de concorrência.

## Fontes oficiais consultadas

Todos os links fixam o mesmo commit, inclusive documentação, evitando atribuir divergências a
versões diferentes:

- [Tipos de scan](https://github.com/arsenetar/dupeguru/blob/db097a030150b3d4ea9f492b85e7e4e4bcb3f789/help/en/scan.rst)
- [Pastas e estados](https://github.com/arsenetar/dupeguru/blob/db097a030150b3d4ea9f492b85e7e4e4bcb3f789/help/en/folders.rst)
- [Grupos, revisão e ações](https://github.com/arsenetar/dupeguru/blob/db097a030150b3d4ea9f492b85e7e4e4bcb3f789/help/en/results.rst)
- [Conteúdo e agrupamento](https://github.com/arsenetar/dupeguru/blob/db097a030150b3d4ea9f492b85e7e4e4bcb3f789/core/engine.py)
- [Scanner](https://github.com/arsenetar/dupeguru/blob/db097a030150b3d4ea9f492b85e7e4e4bcb3f789/core/scanner.py)
- [Hash/cache e arquivos](https://github.com/arsenetar/dupeguru/blob/db097a030150b3d4ea9f492b85e7e4e4bcb3f789/core/fs.py)
- [Ações e hardlinks](https://github.com/arsenetar/dupeguru/blob/db097a030150b3d4ea9f492b85e7e4e4bcb3f789/core/app.py)
- [Resultados e falhas](https://github.com/arsenetar/dupeguru/blob/db097a030150b3d4ea9f492b85e7e4e4bcb3f789/core/results.py)
- [Resolução de conflitos](https://github.com/arsenetar/dupeguru/blob/db097a030150b3d4ea9f492b85e7e4e4bcb3f789/hscommon/conflict.py)
- [Licença GPLv3](https://github.com/arsenetar/dupeguru/blob/db097a030150b3d4ea9f492b85e7e4e4bcb3f789/LICENSE)

Licença verificada antes da implementação: GPLv3 no LICENSE e cabeçalhos dos módulos.
Não foi copiado, incorporado ou adaptado código do dupeGuru, nem adicionado como dependência.
As ideias de referência imarcável e revisão separada de ação informaram o contrato. Eventual
incorporação de código exigirá avaliar a compatibilidade de licenças/distribuição; não se presume
que estudar código aberto autoriza incorporá-lo sem obrigações.
