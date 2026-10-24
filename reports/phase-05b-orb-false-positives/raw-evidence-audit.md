# Auditoria complementar dos artefatos brutos — 2026-10-24

Resultado: **PASS** para integridade da transferência e concordância dos
artefatos recebidos. O encerramento científico da 05B permanece **PASS WITH
RESERVATIONS** pelos limites de proveniência e reprodução descritos abaixo.
Este adendo complementa o [encerramento](closure.md), sem reescrever o estado
histórico de indisponibilidade registrado em 2026-10-23.

## Recebimento e integridade

Pacote: `phase-05b-evidence-20261024-105856.tar.gz`.
SHA-256 verificado contra o valor informado pelo operador:
`58e19f4bb0c56d05644993519497e01e62e8e7750253e3b58dc3411e891bc6c2`.

A inspeção anterior à extração encontrou exatamente nove arquivos regulares:
oito artefatos e `SHA256SUMS`. Sem nomes duplicados, links, caminhos absolutos,
travessia de diretórios ou arquivos especiais. Extração com filtro Python `data`.
Os oito hashes coincidiram com o manifesto. Hashes asseguram concordância dos
bytes recebidos; não autenticam por si a criação original dos diagnósticos.

| Artefato | Bytes | SHA-256 |
|---|---:|---|
| `orb-mutual-confirmations.json` | 6593 | `5ec32f6888cdcffaf8972086ad0692ae0c9568d2664573d38be521d6aabdb866` |
| `geometry-diagnostics/geometry-comparison.json` | 9881 | `e0528a2158840656b0edc8a783d5fa9b6baa0e9660225b38b0a6048365b146ca` |
| `geometry-diagnostics/FP-202600-direct.png` | 2477784 | `192b34cc3abd588d8a3e2cf6646bcc251cff98e4843ebbe1571fb1c673e7f0e4` |
| `geometry-diagnostics/FP-202600-mutual.png` | 2476264 | `bc36cb8e3bc75b1a68f99a10431f1d2570c1a9ce4e64e518ac3d1784083c8a80` |
| `geometry-diagnostics/FP-207800-direct.png` | 2527096 | `4a1f675c5fe9cd76238cd9f06ef262018353ffebb0f9f05d0c227989659a7576` |
| `geometry-diagnostics/FP-207800-mutual.png` | 2517896 | `087ca910112950aeefe56635eddb15ca6a7655c0208d8d63a7ca94990b009e27` |
| `geometry-diagnostics/TP-214900-direct.png` | 2859936 | `e140ca704e8d8d1bf8f4b5472b3a80aaa24e4efed124ccac52b00f123d29a1a7` |
| `geometry-diagnostics/TP-214900-mutual.png` | 2861864 | `51750fa25f1bdb4f317aaba83fd96fed911fa2274fb4a10389253cf9651d93ba` |

## Verificações executadas

- Ambos os JSONs foram lidos e cada um contém exatamente os três pares esperados.
- Configurações ORB e de verificação e versão OpenCV reportada coincidem com
  `measurements.json`; os parâmetros por par também coincidem.
- Comparação exata de todos os campos consolidados por par: classificação,
  caminhos normalizados para relativos, hashes das fontes registrados, contagem
  de keypoints, todos os campos `direct` e todos os campos `mutual`. Sem divergência.
- A evidência direta completa de `orb-mutual-confirmations.json` coincide com
  `original_evidence` de `geometry-comparison.json` em cada um dos três pares.
- Os seis PNGs passaram em `Pillow.Image.verify()` e decodificação completa;
  todos têm dimensões 1824 × 768. Os seis foram inspecionados visualmente.
- O pacote não fornece lista completa das decisões sobre os 285 candidatos:
  o total continua corroborado pela linha do relatório do Experimento 04,
  não por uma nova enumeração dos 285 resultados neste pacote.

## Inspeção visual

A consulta exibida à esquerda é uma composição com múltiplas fotografias.
Em ambas as visualizações de FP-202600, as correspondências desenhadas se
concentram na faixa de arquitetura à direita dessa composição. Em FP-207800,
concentram-se na região superior com arquibancada. No TP-214900, distribuem-se
pela região central das árvores. O padrão qualitativo é consistente entre os
painéis diretos e recíprocos e corrobora as observações anteriores.

As figuras sustentam correspondência visual parcial. Não demonstram, sozinhas,
igualdade de pixels, cadeia de derivação ou identidade de captura. Não foi
contada manualmente cada linha nem reestimada a homografia a partir dos PNGs.
A classe FP permanece relativa à referência histórica de capture_id do dataset.

## Limites restantes e escopo público

Os JSONs brutos e as visualizações agora estão disponíveis para esta auditoria;
a ressalva anterior sobre sua ausência foi resolvida. Os originais do corpus,
o script independente de geração e uma reprodução completa do ambiente não
foram fornecidos. Os hashes das fotografias continuam sendo valores registrados,
sem nova conferência contra os bytes dessas fotografias.

Nenhuma execução ORB/RANSAC ou avaliação da 05C foi realizada. Não houve ajuste
de thresholds, mudança de referência, algoritmo ou política de retenção.
O operador informou preservação das oito cópias verificadas fora de `/tmp`;
essa persistência na workstation não foi inspecionada remotamente.

Somente este adendo textual e seus links são destinados ao GitHub. O pacote,
os JSONs brutos com caminhos pessoais e as seis imagens permanecem fora do
conteúdo versionado. A 05C ainda requer inventário do corpus, referências e
partições por família antes de qualquer execução ou recomendação de produção.
