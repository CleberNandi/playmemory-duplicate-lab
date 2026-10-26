# Quarentena reversível exata v1

Incremento de 2026-10-26, a partir de `4a93464` da branch de revisão.
A main remota foi verificada em `96b2144`; nenhuma branch ORB foi incorporada.
Cópia local limpa encontrada no Work e nova worktree isolada criada para esta entrega.
Nenhum acesso à workstation Arch, VM Sony, fotos reais, corpus ou backups.
Os três documentos de plano, comparação e handoff foram lidos; não se repetiu o estudo do dupeGuru.

## Contrato escolhido antes da implementação

- Linux, `renameat2(RENAME_NOREPLACE)`, mesmo filesystem. Sem fallback para copy/unlink,
  sem exclusão e sem substituição. Filesystems/dispositivos diferentes são bloqueados.
- Autorização separada: ID exato do plano, lista ordenada completa de ações e reconhecimento
  de acesso exclusivo. Autoriza mover e restaurar esses caminhos. O plano permanece dry-run;
  `ready_for_review` continua sem autorizar operações. Checksum não autentica operador.
- JSON de execução limitado a 16 MiB, sem campos repetidos, NaN ou constantes não JSON.
  Schema v1, campos conhecidos, inventário, identidades, grupos, decisões, proteção,
  caminhos canônicos e destinos derivados são validados. Revalidação integral antes da
  autorização e da primeira execução deve reconstruir exatamente o plano aprovado.
- Preservado e candidato são verificados por identidade e SHA-256 antes de cada movimento;
  preservado também após cada ação. Nunca se move o preservado nem um membro protegido.
- Symlinks/ancestrais com symlinks e hardlinks são bloqueados; heurística de sidecars continua
  conservadora. Revisão externa de catálogos é obrigatória. Não atualiza catálogos externos.
- Journal SQLite privado na quarentena: manifesto com origens/destinos/identidades/digests,
  estados por ação, eventos com sequência SQLite/rowid, timestamp UTC e falhas. Intenções são
  confirmadas com `synchronous=FULL` antes de renomear; diretórios recebem fsync.
- Estado inicial do journal é preparado em arquivo temporário privado e publicado sem
  sobrescrita, antes de movimentar. Interrupção no bootstrap pode deixar `.exact-bootstrap-*`;
  esses resíduos não autorizam ações e não são usados na retomada. Não são apagados automaticamente.
- Retomada reconcilia intenção e caminhos: origem presente/destino ausente permite tentar;
  origem ausente/destino com mesmo inode e digest permite confirmar. Ambos presentes ou
  ausentes são ambíguos e bloqueiam. Ações concluídas são verificadas sem renomear novamente.
- Restauração exige origem livre, pasta original existente, mesmo filesystem e conteúdo
  verificado. Link quebrado também é ocupação. Não cria novamente pastas originais removidas.
  Após iniciar restauração, só se permite continuar restaurando; novo movimento exige novo plano.
- Operações não formam transação de lote: uma falha para imediatamente e deixa ações concluídas
  no journal. O operador pode retomar ou restaurar; não há rollback automático nem promessa de
  atomicidade entre filesystems.

## Limites operacionais e de confiança

Use somente artefatos locais produzidos pelo programa e mantenha plano, autorização e journal.
Artefatos, journal e HTML têm caminhos privados e não devem ser publicados. Eles não são
assinaturas nem uma fronteira contra alguém que possa reescrever plano, autorização e journal.
Não execute com sudo ou como serviço privilegiado.

Acesso exclusivo é condição obrigatória: feche importadores, sincronizadores, editores e outros
programas que possam alterar o conjunto. `flock` na raiz impede duas execuções do Lab na mesma
raiz, mas não coordena raízes sobrepostas nem escritores externos. Validação lexical e hashes
não protegem contra um escritor adversarial que troque ancestrais entre checagem e syscall.
A proteção contra sobrescrita do destino é do kernel; ela não elimina essas outras corridas.

Quarentena deve pertencer ao operador e não aceitar escrita de grupo/outros. Pastas novas usam
modo 0700 e journal usa 0600; a umask pode restringir mais. Permissões POSIX ainda podem impedir
rename/fsync e isso bloqueia a ação. Nada altera proprietário, modo ou ACL de arquivo.
Renomear no mesmo filesystem mantém inode, conteúdo, mtime, ACLs e xattrs do arquivo; ctime muda
pela operação, e atime pode mudar na leitura. Na recuperação de arquivos já movidos, ctime não
é comparado com o scan; device/inode/tamanho/mtime/nlink e SHA-256 continuam exigidos.
Não se certifica preservação de metadados de diretórios, nem detecção de toda mudança de ACL.

Conteúdo verificado e diretórios são sincronizados, mas durabilidade depende de SQLite,
filesystem local e hardware honrarem fsync. NFS, FUSE/cloud mounts e armazenamento que não
honre essas garantias não foram homologados. Não usar neles nesta versão. Perda/corrupção do
journal exige intervenção; o programa não adivinha ações nem apaga dados para reconstruí-lo.
O preservado deve continuar íntegro inclusive na restauração; se faltar, interrompa e recupere
com intervenção técnica, preservando todas as cópias restantes.

## Demonstração sintética reproduzível

```bash
uv sync --locked
uv run pytest
uv run ruff check .
uv run python examples/synthetic_quarantine.py
```

O exemplo cria somente bytes sintéticos em diretório temporário, chama scan → decisão humana
sintética → plano → check → autorização → movimentação → restauração, verifica caminhos/conteúdo
nas duas fronteiras e remove apenas o diretório temporário ao terminar. Não aponta ao acervo.
Arquivos `.jpg` sintéticos não precisam ser JPEG válidos: a igualdade é binária.

## Homologação posterior no Arch — não executada pelo Work

1. Trazer a branch `feat/exact-reversible-quarantine` para worktree isolada, sem merge na main.
   Executar os quatro comandos sintéticos acima antes de tocar no conjunto de estudo.
2. Fechar programas que possam modificar o conjunto. Confirmar que são cópias de estudo.
   Escolher quarentena privada fora do acervo e no mesmo filesystem. Não reutilizar destinos
   de outra sessão. Preservar as evidências antigas; elas não autorizam a nova execução.
3. Criar novo `scan.json` e plano revisado em diretório privado novo. Reutilizar somente a
   intenção da decisão humana, conferindo os caminhos atuais. Conferir protegidos e catálogos.
   Exemplo com placeholders absolutos (substituir antes de executar):

```bash
uv run duplicate-lab exact-scan /acervo-de-estudo --output /revisao-nova/scan.json
uv run duplicate-lab exact-plan /revisao-nova/scan.json \
  --decisions /revisao-nova/decisions.json --dependencies-reviewed \
  --quarantine-dir /quarentena-nova --output /revisao-nova/plan.json
uv run duplicate-lab exact-check /revisao-nova/plan.json
uv run duplicate-lab exact-gallery /revisao-nova/plan.json --output /revisao-nova/galeria.html
```

4. Revisar o plano/galeria e copiar seu ID integral. Somente após decisão explícita do operador:

```bash
uv run duplicate-lab exact-authorize /revisao-nova/plan.json \
  --confirm-plan-id ID_INTEGRAL_REVISADO --exclusive-access \
  --output /revisao-nova/authorization.json
uv run duplicate-lab exact-quarantine /revisao-nova/plan.json \
  --authorization /revisao-nova/authorization.json
```

5. Conferir o resultado por ação exibido no terminal, manter o journal, verificar preservado
   na origem e candidatos exclusivamente na quarentena. Em interrupção, repetir exatamente o
   último comando com os mesmos artefatos; não regenerar plano para a sessão parcialmente movida.
   `exact-check` é para antes da movimentação: após mover, o plano necessariamente fica stale.
6. Para restaurar/retomar restauração, por decisão do operador:

```bash
uv run duplicate-lab exact-restore /revisao-nova/plan.json \
  --authorization /revisao-nova/authorization.json
```

Conflitos param a sessão e preservam o ocupante; resolver o conflito fora da ferramenta e
retomar. Nunca apagar automaticamente o ocupante. Depois de restaurar, conferir hashes e todos
os caminhos; manter journal e evidências. CLI retorna 0 ao concluir, 2 em falhas esperadas.
Para inspecionar o journal, abrir sua cópia em modo somente leitura no SQLite e consultar
`manifest`, `actions` e `events ORDER BY rowid`; não editar essas tabelas.

## Validação executada

Work/Linux, Python 3.13.16, dependências do lockfile. A suíte passou de 94 para 133 testes.
Inclui ciclo API/CLI, preservado protegido, mudanças/remoções, symlinks/hardlinks/sidecars,
conflitos de arquivo/diretório/link quebrado, destino criado entre verificação e rename,
interrupções antes/depois dos renames e após confirmação, falha parcial, retomada, restauração
livre/conflitante, exclusão mútua entre processos do Lab, rejeição de autorização/schema/JSON,
falhas injetadas EACCES/ENOSPC/EIO e bloqueio real entre filesystem temporário e `/dev/shm`.
Quatro casos encerram subprocessos com os._exit nas fronteiras de intenção/rename,
sem cleanup Python, e verificam a recuperação. O exemplo sintético completo também foi executado, com dois movimentos e duas restaurações.
Ruff e `git diff --check` aprovados.

Falhas injetadas não equivalem a disco fisicamente cheio, corte de energia ou falha de hardware.
Não foram executados: Arch, fotografias do operador, catálogos externos, Windows, crash físico,
NFS/FUSE, testes completos de ACL/xattrs ou todos os pontos internos de falha do SQLite.
A homologação no Arch permanece pendente; testes sintéticos não autorizam fotos reais.
