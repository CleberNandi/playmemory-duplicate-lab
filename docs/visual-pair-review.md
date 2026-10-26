# Revisão humana de um par JPEG

Primeiro incremento visual: par escolhido explicitamente pelo operador, sem varrer novamente
um corpus. Objetivo: inspecionar candidatos a redimensionamento/recompressão; não reconhecer
automaticamente a transformação. Sem ORB, busca de rotação, novos thresholds ou operações de
arquivo. Rotação/recorte/edição/sequências/vídeo permanecem fora da homologação deste incremento.

## Uso no Arch

Na branch `feat/visual-pair-review`, após fetch/switch e `uv sync --locked`:

```bash
uv run duplicate-lab visual-pair /caminho/estudo/a.jpg /caminho/estudo/b.jpg \
  --output-dir /caminho/revisoes/par-01
xdg-open /caminho/revisoes/par-01/gallery.html
```

Use dois JPEGs distintos do conjunto de estudo, por exemplo as versões multi-resolução já
identificadas. A saída precisa ser nova e fora das pastas das imagens. Não substituir os
placeholders por caminhos de originais oficiais. O programa não abre navegador automaticamente.
Os arquivos de entrada permanecem no lugar; a saída é persistente e privada.

Após comparar, registrar a avaliação em uma NOVA pasta:

```bash
uv run duplicate-lab visual-pair /caminho/estudo/a.jpg /caminho/estudo/b.jpg \
  --output-dir /caminho/revisoes/par-01-avaliado \
  --decision accepted_candidate --reason 'Quadro compatível; resolução diferente'
```

Valores: `pending`, `accepted_candidate`, `rejected_candidate`, `uncertain`. Motivo obrigatório
quando diferente de pending. Aceitar significa manter como candidato para revisão, sem afirmar
mesma captura. Cada execução recalcula hashes e registra os arquivos efetivamente lidos; não
altera a revisão anterior. Não há assinatura ou autorização operacional nesses JSONs.

## Evidência e limites

- `review.json`: SHA-256 por arquivo, igualdade binária independente da avaliação humana,
  dimensões armazenadas, bytes, métricas e motivo humano.
- `gallery.html`: prévias lado a lado, autocontidas, com JSON escapado para leitura.
- pHash apenas na orientação EXIF normalizada; SSIM/MAE em cinza, quadro integral deformado
  para 512 × 512, como o comparador existente. Diferença de proporção pode distorcer métricas.
- Prévia de até 360 × 240 não substitui inspeção dos arquivos em resolução integral. Dimensões
  são as armazenadas no JPEG, antes da normalização EXIF da prévia.
- Links são rejeitados; JPEGs inválidos e alterações observáveis durante leitura bloqueiam
  publicação. Fechar escritores externos. Não há transação entre leitura e escrita de relatórios;
  uma falha de escrita pode deixar pasta parcial, que deve ser preservada e refeita em outra pasta.
- HTML/JSON incluem caminhos privados e prévias: não publicar no GitHub.
- Não gera plano exato, preferência de preservação, autorização, quarentena ou restauração.

Critério de homologação: conferir dois JPEGs conhecidos redimensionados/recomprimidos e um par
de cenas distintas; abrir HTML, comparar dimensões/prévias, registrar aceite/rejeição com motivo,
conferir que hashes e caminhos das entradas permanecem iguais. Homologação visual no Arch ainda
pendente; testes sintéticos não certificam acurácia em fotografias reais.

## Convergência

O Photo Manager consumirá o conceito de avaliação humana vinculada às localizações e hashes,
com identidades de captura e anotações próprias. Esta CLI/galeria é um experimento de contrato,
sem interface definitiva ou serviço independente. Não importar JSON como autorização de ação.
