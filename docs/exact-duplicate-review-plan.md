> Atualização 2026-10-26: este documento registra o incremento dry-run original.
> A execução agora tem contrato separado em [quarentena reversível](exact-reversible-quarantine.md).
> O plano continua sem autorizar ações; as afirmações históricas de ausência de executor
> referem-se à entrega de 2026-10-24.

# Duplicatas binárias: snapshot e plano de revisão v1

## Decisão e auditoria

Base verificada: `main` `96b214475dc56fa4e828f9c0bf9eb3b3b6db3a3f`, versão 0.2.2.
As branches experimental e de investigação foram inspecionadas por referência, sem integração.
A árvore da main não continha AGENTS.md. Cópia isolada no Work, sem acesso à workstation,
à VM Sony, a fotografias reais ou ao corpus histórico. Não foi repetida a auditoria 05B.

Já existiam inventário JPEG, pré-filtro por tamanho, SHA-256 com detecção de alterações
observáveis, grupos exatos, relatórios JSON/CSV/HTML e preferências de retenção sem operações.
Faltavam snapshot persistido com identidade, seleção revisável ligada ao conteúdo,
proteção executável no plano, destinos propostos, bloqueios e revalidação do plano.
O inventário antigo resolve symlinks; não serve como manifesto de caminhos para separação.

**Escolha: combinar ferramentas existentes com um plano próprio mínimo.**

| Alternativa | Benefício | Custo/limite |
| --- | --- | --- |
| dupeGuru diretamente | Revisão e marcação prontas; menor esforço para uso humano | Não fornece o contrato de plano/revalidação desejado para o Photo Manager |
| Fluxo próprio completo | Controle do ciclo inteiro | Recria UI e execução antes de validar a necessidade |
| dupeGuru para revisão + plano mínimo no Lab | Reaproveita experiência pronta; mantém rastreabilidade local | Revisão em duas ferramentas, sem sincronização automática de marcações |

O Lab reutiliza `find_exact_groups`, `sha256_file` e `build_retention_report`.
A descoberta específica preserva caminhos lexicais, não segue symlinks e trabalha com bytes,
sem decodificar JPEG e sem pipeline perceptual. Logo, um arquivo inválido chamado `.jpg`
também pode ser duplicata binária; isso não certifica validade da imagem.
Nenhuma alteração de thresholds, ORB ou Fase 05C. Nenhuma UI definitiva ou integração ao
Photo Manager foi implementada. O plano JSON é a fronteira experimental para essa evolução.

A Retention Policy permanece intacta: `others` não era uma autorização de movimentação,
e diretórios protegidos apareciam como aviso. O adaptador do plano aplica proteção explícita,
excluindo todos os membros protegidos dos candidatos, mesmo quando não são o `keep`.
Conflito/empate de regras continua sem vencedor; decisão humana explícita pode escolher um
membro, com motivo registrado. Tamanho/qualidade/datas não escolhem o exemplar.

## Uso local

```bash
uv sync --locked
uv run duplicate-lab exact-scan /acervo --output /revisao/scan.json
uv run duplicate-lab exact-plan /revisao/scan.json \
  --quarantine-dir /quarentena --output /revisao/plan-inicial.json
```

A primeira execução do plano pode ficar bloqueada, intencionalmente. Inspecione `groups`,
`keep`, `members`, `protected`, `dependencies`, `candidates` e `blockers` no JSON.
Os arquivos contêm caminhos locais privados; não os publique nem os adicione ao Git.
São escritos somente fora do acervo e com criação exclusiva, sem sobrescrita.

Para escolher manualmente, crie `/revisao/decisions.json`, usando o SHA-256 real do grupo:

```json
{
  "SHA256_DO_GRUPO": {
    "keep": "biblioteca/foto.jpg",
    "reason": "Caminho usado pelo catálogo, conferido pelo operador"
  }
}
```

`keep` é relativo à raiz do scan. Só aceita membro do próprio grupo. Alternativamente,
use a política de retenção v1 já existente. Se houver decisão humana para o grupo, ela
precede a preferência da regra; proteção e demais bloqueios continuam prevalecendo.

```bash
uv run duplicate-lab exact-plan /revisao/scan.json \
  --decisions /revisao/decisions.json \
  --retention-policy /revisao/retention-policy.json \
  --dependencies-reviewed \
  --quarantine-dir /quarentena --output /revisao/plan-revisado.json
uv run duplicate-lab exact-check /revisao/plan-revisado.json
```

Use `--dependencies-reviewed` somente após conferir catálogos, referências externas e
organização de pastas. É registro de revisão humana, não detecção automática nem autorização.
Não remove bloqueios de sidecars conhecidos. Sem a opção, a pendência fica explícita.
Escolhas/política alteradas exigem gerar outro plano; não edite diretamente o artefato selado.

`exact-scan`/`exact-plan`: código 0 significa artefato gerado, inclusive plano bloqueado.
`exact-check`: 0 somente para plano inalterado, com grupos e todos `ready_for_review`;
2 para bloqueio, divergência, plano sem grupos ou erro. Mesmo com código 0, não há autorização.
A revalidação imprime o estado atual e não modifica o plano original.

## Contrato e limites

- Snapshot v1: raiz absoluta, timestamp UTC, extensões, inventário com caminhos relativos,
  device/inode/size/mtime_ns/ctime_ns/nlink, exclusões de symlinks e grupos SHA-256.
  Arquivos de tamanho exclusivo não precisam de hashing. Default: jpg/jpeg;
  `--extensions` permite outras extensões. Não descobre automaticamente todos os formatos.
- Plano v1: snapshot completo, cópia da política, decisões/motivos, revisão de dependências,
  membros protegidos, `keep`, origem da escolha, candidatos e bloqueios por grupo.
  Sem vencedor, não há candidatos. Várias referências protegidas ficam todas visíveis.
- Destino proposto: `quarentena/SHA256/caminho-relativo`. Isso distingue nomes iguais em
  pastas diferentes. A raiz da quarentena não pode sobrepor o acervo. Nada é criado nela.
  Arquivo, diretório, symlink quebrado ou ancestral impeditivo bloqueiam o destino.
- Symlinks de arquivo/diretório são excluídos e listados no scan. Raízes/ancestrais com
  symlinks são rejeitados. Hardlinks (`nlink != 1`) permanecem visíveis e bloqueiam o grupo;
  nomes para um mesmo inode não são cópias independentes nem economia de espaço somável.
- A geração/revalidação verifica identidade e lê novamente SHA-256 de todos os membros
  dos grupos, inclusive o preservado. Remoção, substituição, conteúdo divergente,
  alterações observáveis de metadados ou link count bloqueiam o grupo. Um novo scan e nova
  revisão são necessários após mudanças; não se atualiza silenciosamente a evidência.
- Dependências conhecidas: vizinhos com mesmo stem, ou prefixo `nome-completo.` (ex.:
  `foto.xmp`, `foto.jpg.xmp`), sem distinção de caixa, bloqueiam o grupo. Heurística
  conservadora, com falsos bloqueios possíveis; não resolve catálogos, referências em banco,
  sidecars com outros nomes ou dependências remotas. Não movimenta sidecars.
- Novos arquivos fora dos grupos não são um rescan implícito. Novos sidecars detectáveis e
  conflitos de destino são verificados. Uma mudança externa de catálogo não é observável;
  o operador precisa invalidar/revisar sua confirmação.
- IDs são checksums de JSON canônico para detectar alterações acidentais, não assinatura,
  esquema de autorização ou fronteira contra artefatos maliciosos. Use artefatos locais
  produzidos pelo programa. Não há garantias de concorrência com um escritor adversarial;
  esta checagem de leitura não poderá substituir o protocolo de execução futuro.
- `ready_for_review` descreve revisão pendente; `action_authorized=false` e
  `operations_performed=false` em todos os planos. Nenhuma função move, renomeia ou exclui.

## Contrato mínimo exigido antes de execução real (ainda não implementado)

1. Autorização explícita ligada ao ID exato do plano e às ações aprovadas; schema rigoroso
   e rejeição de caminhos, flags, versões ou destinos inesperados.
2. Revalidar todos os membros, o preservado e os destinos imediatamente antes de cada ação.
   Não remover o preservado/protegidos; interromper o grupo se não restar cópia verificada.
3. Reservar destino de forma exclusiva, sem check-then-overwrite. Revalidar ancestrais/links
   com operações adequadas ao sistema operacional, incluindo corridas e limites de nomes.
4. Journal durável por operação, antes/depois, com origem, destino, identidade, SHA-256,
   resultado e falha. Retomada idempotente deve reconciliar journal e ambos os caminhos,
   sem assumir que interrupção significa falha ou sucesso.
5. Entre filesystems, cópia para destino exclusivo, verificação/durabilidade do conteúdo e
   só então remoção autorizada da origem. Não prometer atomicidade entre filesystems.
   Definir explicitamente preservação de permissões, timestamps, ACLs e atributos relevantes.
6. Restauração por manifesto/journal, revalidando conteúdo na quarentena e criando a origem
   exclusivamente. Se a origem existir, bloquear e pedir resolução; jamais sobrescrever.
7. Testes próprios de interrupção em cada fronteira, permissões, disco cheio, concorrência,
   conflitos e restauração. Nesta entrega só há testes de leitura/dry-run sintéticos.

A futura execução merece escopo próprio. O plano atual não deve ser consumido por um script
improvisado de `mv`/`rm`, pois ainda não fornece essas garantias.

## Validação desta entrega

Executada em 2026-10-24, Linux no Work, CPython 3.13.16, dependências do `uv.lock`:

- `uv sync --locked`: concluído, sem alteração do lockfile.
- Baseline antes do incremento: 70 testes aprovados.
- `uv run pytest` após o incremento: **90 passed** (20 casos adicionais sintéticos).
- `uv run ruff check .`: aprovado; `git diff --check`: aprovado.
- `uv run duplicate-lab --help`: comandos novos disponíveis.
- Roundtrip CLI scan/plano/check, incluindo remoção posterior: testado em diretório temporário.
- Casos: nomes diferentes/conteúdo igual; mesmo nome/conteúdo diferente; três cópias;
  regra e decisão humana; conflito de regra; proteção parcial/total; conteúdo alterado,
  remoção, substituição por symlink e novo hardlink após scan; symlinks de arquivo/diretório
  e quebrados; sidecars; conflitos no destino (arquivo, diretório, link quebrado, ancestral
  arquivo); checksum; saída sem sobrescrita/fora do acervo; raiz/saída symlink rejeitada.

Não executados: dupeGuru, workstation Arch, Windows, corpus histórico, fotografias reais,
movimentação, restauração, interrupção de execução ou testes entre filesystems.
Não há declaração de PASS para essas capacidades. A aprovação refere-se somente ao dry-run.

## Visualização do plano em HTML local

`duplicate-lab exact-gallery plan-reviewed.json --output galeria.html` reaproveita o renderer
existente. O plano é revalidado antes e depois da geração das miniaturas; qualquer divergência
impede gravar a galeria. Um plano bloqueado ainda pode ser mostrado quando está inalterado,
com seus bloqueios e escolhas pendentes visíveis. Não exige que o plano autorize ações.

Mostra grupos expansíveis, busca por todos os nomes do grupo, miniaturas incorporadas,
preservado primeiro, candidatos, protegidos e motivo da escolha. Nesta modalidade, não há
pHash/SSIM/ORB nem avaliação de qualidade. Arquivos binariamente elegíveis não são certificados
como imagens válidas: uma miniatura que não puder ser decodificada fica indisponível.
Dimensões não fazem parte deste snapshot e aparecem como não disponíveis na galeria.

O output deve ser novo, fora do acervo e sem symlinks nos ancestrais. O relatório antigo não é
substituído. O HTML permanece privado e autocontido. Não há botões de movimentação nem edição
do plano; busca/expansão só alteram a exibição. Um HTML já aberto é um retrato estático e não
revalida conteúdo em tempo real. A implementação usa as mesmas limitações de concorrência do
revalidador dry-run e não constitui protocolo de execução seguro.

Validação adicional: 94 testes aprovados (quatro novos para galeria do plano), Ruff aprovado.
Os casos cobrem miniaturas e papéis, escape de nomes/motivos, ausência de dependências de rede,
CLI, plano bloqueado, plano desatualizado, saída fora do acervo e criação sem sobrescrita.
A verificação visual em navegador não foi executada no Work: o Chromium headless não estava
instalado e seu download falhou. A abertura, busca e expansão deverão ser conferidas pelo
operador no navegador do Arch. Não há declaração de PASS para esse teste visual.
