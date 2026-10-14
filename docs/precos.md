# Preços de peças novas no Brasil

O scanner pode devolver uma estimativa em reais para qualquer categoria do catálogo. Um preço
somente aparece quando existe pelo menos uma oferta revisada do **mesmo identificador**
no catálogo, observada nos últimos 14 dias. A ausência do campo significa que não há
base recente suficiente; não significa que o produto custa zero.

O valor usa o preço regular anunciado, sem desconto condicionado a Pix, boleto ou cupom,
e sem frete. Apenas peças novas entram no cálculo. Se houver mais de uma loja, o serviço
usa a oferta mais recente de cada loja e calcula a média aritmética. Uma loja não ganha
peso extra por ter várias coletas. `price_offer_count` informa quantas lojas entraram;
quando vale 1, `estimated_price_brl` é um preço observado, não uma média de mercado.
`price_observed_at` é o horário da observação mais recente, em UTC.
`price_status` vale `observed` para uma loja, `average` para duas ou mais,
`reference_only` quando existe apenas uma referência histórica, ou `unavailable`
quando não há nenhum preço. Sem oferta atual em R$, os campos numéricos
de preço são omitidos em `/scan` e `/lookup`; em `/specs/{id}` são `null`.
Por exemplo, a GA-Z77X-UD5H tem `price: null` na fonte
Kaggle e não deve receber o preço da variante GA-Z77X-UD5H-WB nem de uma usada.

### Referência histórica em moeda original

Quando há uma fonte identificada para o **modelo exato**, o JSON também pode incluir
`reference_price_amount`, `reference_price_currency`, `reference_price_context`,
`reference_price_source_url` e, quando conhecida, `reference_price_date`. Esses campos
são separados de `estimated_price_brl`. `reference_only` em `price_status` significa
que há uma referência, mas nenhuma oferta nova recente no Brasil.

A GA-Z77X-UD5H tem [preço de US$ 189,99 documentado em uma análise de 09/05/2012](https://www.bit-tech.net/reviews/tech/motherboards/gigabyte-ga-z77x-ud5h-review/1/).
É um preço histórico nos EUA, **não** uma cotação ou preço de venda atual no Brasil.
Além dela, o projeto associa preços em EUR do [dataset PCPartPicker Parts](https://huggingface.co/datasets/Doshiba/pcpartpicker-parts-dataset)
somente aos produtos previamente cruzados por identificador exato para as imagens.
Na revisão fixada, são 428 associações em EUR e uma referência histórica em USD.
O dataset informa que os preços podem estar ausentes ou desatualizados e não fornece
data por oferta; por isso o contexto fica `dataset_snapshot` e a data é omitida.

O manifesto é reproduzido a partir da revisão fixa do dataset com:

```bash
poetry run python -m scan_hardware.reference_prices
```

O comando usa o arquivo JSONL já baixado para as imagens e só publica registros com
produto e URL exatos. O manifesto empacotado vai junto no Docker e no Git; nenhum
acesso à rede é necessário na inicialização do serviço.

## Importar ofertas revisadas

Crie `data/import/prices/manifest.json` com este formato (valores apenas ilustrativos):

```json
{
  "offers": [
    {
      "item_id": "cpu-dd697180a182948f05745f01",
      "identifier": "100-100000065BOX",
      "retailer": "Example Store",
      "source_url": "https://example.com/product/100-100000065box",
      "price_brl": "1299.90",
      "observed_at": "2026-10-13T12:00:00Z",
      "condition": "new",
      "payment": "standard"
    }
  ]
}
```

Substitua a loja, URL, preço e horário por dados conferidos. `condition` e `payment`
podem ser omitidos, pois os únicos valores aceitos são `new` e `standard`. O importador
confere formato, data e associação do código ao item; registros inválidos vão para o
relatório de rejeição e os válidos continuam. Reimportar o mesmo arquivo não duplica
observações. Relatórios versionados ficam em `data/processed/price-import/`.

O repositório inclui [três ofertas revisadas em 13/10/2026](../examples/prices-reviewed-2026-10-13.json),
uma de cada categoria, como exemplo reproduzível. Copie esse arquivo para
`data/import/prices/manifest.json` antes do primeiro teste. A validade dos valores
termina 14 dias após `observed_at`; confira preços e disponibilidade antes de renovar
as datas. Não altere apenas o horário de uma oferta antiga.

Com Poetry, após importar o catálogo de peças:

```bash
poetry run python -m scan_hardware.price_import --manifest data/import/prices/manifest.json
```

O Docker Compose monta `data/import/prices/` em modo leitura e importa o manifesto
automaticamente na inicialização, depois de preparar o catálogo. As ofertas ficam
no PostgreSQL do volume `postgres_data`. Atualize o manifesto com ofertas recém-conferidas
e reinicie o serviço para importar o novo lote. Os preços vencem após 14 dias mesmo que
o contêiner continue ligado.

## Limites da cobertura

O conjunto Kaggle traz alguns preços históricos, sem evidência de serem preços atuais
em reais; eles não alimentam esta estimativa. Sem uma fonte autorizada para coleta em
escala, apenas os modelos com ofertas revisadas terão preço. As três ofertas de exemplo
servem para testar o fluxo completo e não representam cobertura do catálogo.
O diretório `data/` não é versionado no Git; copie o manifesto revisado para o servidor
físico quando for implantar.
