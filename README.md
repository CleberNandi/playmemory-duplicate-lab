# PlayMemories Duplicate Lab

Protótipo local, determinístico e somente leitura para descobrir duplicatas exatas e investigar
fotografias visualmente semelhantes. O programa nunca exclui, move, renomeia ou sobrescreve as
fotografias analisadas.

## Instalação e uso

Requer Python 3.13+ e `uv`.

```bash
uv sync --locked
uv run duplicate-lab --help
uv run duplicate-lab inventory /caminho/das/fotos
uv run duplicate-lab scan /caminho/das/fotos --phash-threshold 8
uv run duplicate-lab report /caminho/das/fotos --output-dir /caminho/separado/relatorios --format both
uv run duplicate-lab report /caminho/das/fotos --output-dir /caminho/separado/galeria --format html
uv run duplicate-lab report /caminho/das/fotos --output-dir /caminho/separado/galeria \
  --format html --quality --quality-manifest /caminho/ground-truth.json
uv run duplicate-lab report /caminho/das/fotos --output-dir /caminho/separado/galeria \
  --format html --retention-policy /caminho/retention-policy.json
```

Extensões podem ser configuradas com `--extensions jpg,jpeg`. A normalização estrutural usa uma
imagem cinza limitada a 512 x 512 por padrão; `--comparison-side` aceita valores de 64 a 2048.
Relatórios só são escritos quando `--output-dir` é informado e esse diretório deve estar fora do
acervo. Um arquivo existente não é substituído sem a opção explícita `--overwrite`. O formato
`both` preserva o comportamento JSON+CSV; `all` gera JSON, CSV e HTML.

## Galeria HTML local

A galeria é um único arquivo autocontido, aberto diretamente por `file://`, sem servidor, CDN,
fontes externas ou requisições de rede. Ela oferece busca, filtro, ordenação, detalhes de grupos
SHA-256 e pares visuais. As classificações `similar_image` e `visual_candidate` são apresentadas
como heurísticas sob revisão, nunca como duplicidade confirmada nem recomendação de exclusão.

O HTML contém miniaturas JPEG incorporadas e, portanto, dados derivados de fotografias
potencialmente privadas. Mantenha os relatórios apenas localmente e não os publique. `reports/`
está ignorado pelo Git. Cada miniatura preserva a orientação EXIF, fica limitada a 360 × 240 e a
96 KiB, e jamais incorpora o original em resolução completa. Se uma miniatura não couber nesse
limite ou não puder ser lida, a galeria sinaliza que ela está indisponível.

## Política de retenção de cópias exatas

`--retention-policy` aceita um JSON local com `version: 1` e listas opcionais
`preferred_directories`, `preferred_name_patterns` (expressões regulares), `location_priority` e
`protected_directories`. Todos os diretórios são relativos ao acervo. A política só examina grupos
SHA-256 idênticos e produz `preferred`, `tie` ou `inconclusive`; critérios conflitantes não são
convertidos em pontuação. Diretórios protegidos são destacados e nunca tratados como descartáveis.
Nenhuma recomendação executa operações sobre arquivos, e datas, tamanho, resolução e qualidade
JPEG não participam desta escolha operacional.

Exemplo mínimo:

```json
{
  "version": 1,
  "preferred_directories": ["originais"],
  "preferred_name_patterns": ["^IMG_"],
  "location_priority": ["biblioteca", "importados"],
  "protected_directories": ["backup"]
}
```

## Avaliação técnica experimental

`--quality` calcula indicadores para o HTML sem alterar o resultado do detector nem os contratos
JSON/CSV. Grupos SHA-256 são sempre empate técnico. Outros rankings exigem
`--quality-manifest`, um JSON local fora do acervo que confirma explicitamente versões da mesma
captura:

```json
{
  "version": 1,
  "groups": [
    {"id": "captura-confirmada", "members": ["versao-a.jpg", "versao-b.jpg"]}
  ]
}
```

Os caminhos são relativos ao acervo. Arquivos desconhecidos, grupos sobrepostos e manifestos
dentro do acervo são rejeitados. O rótulo heurístico `similar_image` nunca torna um par elegível e
não há fechamento transitivo.

Os indicadores são dimensões orientadas por EXIF, pixels, proporção, nitidez por Laplaciano em
escala normalizada, luminância média, frações muito claras/escuras, média das tabelas de
quantização JPEG, descontinuidades de blocos experimentais e presença de EXIF. GPS não é lido nem
exibido. Exposição é apenas descritiva; tamanho em bytes não equivale a qualidade.

A política não usa nota de 0 a 100. Comparações par a par formam uma ordem parcial: uma versão só
domina outra com pelo menos duas vantagens relativas e nenhuma desvantagem confiável. Os níveis
de apresentação vêm dessa dominância; dentro do mesmo nível, a ordenação por caminho é apenas
determinística. Mais pixels, isoladamente, não escolhem um vencedor. Nitidez elevada causada por
compressão agressiva não prevalece sobre evidências conjuntas de quantização e blocos. Vantagens
conflitantes produzem `incomparable`; indicadores ausentes podem produzir `inconclusive`.

## Pipeline e interpretação

1. Descobre extensões permitidas, valida o formato real com Pillow e coleta tamanho, dimensões e
   orientação EXIF. Uma falha afeta apenas seu arquivo.
2. Calcula SHA-256 em streaming. Apenas bytes idênticos recebem `exact_duplicate`; o espaço
   redundante mantém um exemplar e soma os demais.
3. Calcula pHash de 64 bits após normalizar EXIF e testa rotações de 0, 90, 180 e 270 graus. Pares
   até o limiar são candidatos, nunca confirmação automática.
4. Redimensiona de maneira limitada e calcula SSIM e MAE na melhor orientação. Evidência forte
   (`SSIM >= 0.80` e `MAE <= 0.10`) recebe `similar_image`; os demais continuam
   `visual_candidate`. Estes limiares são heurísticos, não verdade de referência.

Os resultados são pares independentes. Não há fechamento transitivo, pois A~B e B~C não prova
A~C. Precisão, recall e F1 exigem um manifesto de *ground truth* revisado por uma pessoa.

## Homologação local (61 fotografias)

Execução em `/home/arch-nandi/Imagens/Estudo_fotos_duplicadas/`, em modo somente leitura:

- 61 JPEGs válidos e nenhum arquivo incompatível.
- Um grupo SHA-256 com os 10 arquivos `QVZndERfaTh1TGdqOTNTeS1tU3hweTRM*`: 9 arquivos e
  457.398 bytes redundantes.
- 156 pares visuais não exatos com pHash <= 8, além dos 45 pares internos ao grupo exato.
- Todos os 45 pares `mario_office_*` tiveram pHash 0 e foram classificados `similar_image`;
  SSIM mínimo 0,97329 após normalização.
- Nas comparações contra `photo_quality_95.jpg`, o SSIM foi 0,82410 (qualidade 5), 0,94856
  (qualidade 20), 0,99558 (qualidade 70) e 0,99837 (qualidade 90).
- Os pares candidatos entre `20210329_115149`, `115150` e `115153` tiveram SSIM 0,40019 a
  0,42503 e permaneceram `visual_candidate`, nunca `exact_duplicate` ou `similar_image`.
- Nenhum candidato real teve uma rotação diferente de zero como melhor alinhamento nesta execução;
  o caminho de rotação de 180 graus foi validado pelo teste sintético determinístico.

Os 156 candidatos não exatos diferem em uma unidade da referência experimental anterior de 157.
Isso é compatível com diferenças de versão/normalização, mas não permite concluir ganho ou perda
de qualidade sem um manifesto de verdade de referência.

## Discovery do `photoOrganizer`

O projeto vizinho usa Python, Pillow, Poetry e NetworkX. Ele descobre JPG/JPEG apenas no diretório
corrente, lê `DateTimeOriginal` do EXIF e move fotos para pastas por data. Há também um script que
lê arquivos inteiros para calcular MD5. Não há testes efetivos, logging, licença declarada nem
tratamento consistente de erros.

- Reutilizável diretamente: nenhum código, inclusive pela ausência de licença explícita.
- Reutilizável com adaptação: os conceitos de leitura EXIF via Pillow, filtragem por extensão e
  agrupamento por digest. Aqui foram reimplementados com validação, caminhos `Path`, SHA-256 em
  streaming, tipagem e isolamento de erros.
- Não aplicável: movimentação/organização por data, caminhos Windows, empacotamento PyInstaller,
  NetworkX e o executável gerado.

## Limitações

- pHash, SSIM e MAE continuam sujeitos a falsos positivos e negativos; revisão humana é necessária.
- A normalização para um quadrado distorce a proporção, uma escolha deliberada para comparar
  exportações 4:3 e 16:9 do conjunto; recortes reais ainda podem reduzir as métricas.
- O MVP faz comparação quadrática e recalcula dados a cada execução, adequado ao conjunto de
  pesquisa atual, não a milhões de imagens.
- JPEG é o único formato real aceito por padrão nesta versão, embora extensões sejam configuráveis.
- Metadados EXIF não são usados como prova de identidade.
- Nitidez depende de ruído, textura e sharpening; ampliações artificiais também podem enganá-la.
- Tabelas de quantização e blocos ajudam a comparar versões conhecidas, mas não recuperam com
  precisão a configuração JPEG original e variam entre codificadores.
- A avaliação técnica não mede composição, estética, importância histórica ou intenção de
  exposição, e nunca autoriza exclusão.

## Desenvolvimento

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Os testes criam imagens sintéticas em diretórios temporários. Fotografias pessoais não fazem parte
do repositório nem são necessárias para executar a suíte.
