# Scanner de hardware

Microserviço independente em Python para reconhecer o **modelo ou part number impresso**
em placas-mães, placas de vídeo e processadores. Recebe uma foto, executa OCR local e
procura o identificador em um catálogo PostgreSQL no Docker. O SQLite permanece como
formato de importação local e opção para testes sem Docker. Retorna o item, especificações com fontes
e uma imagem de referência quando existe uma referência adequada. Também aceita busca
direta por texto. Não classifica a aparência de uma peça sem código legível.

Este repositório contém **somente o microserviço**: API, OCR, importação e auditoria do
catálogo, página de teste, testes e documentação. O aplicativo móvel e o backend de um
produto maior são consumidores externos. O [guia de integração](docs/integracao.md)
descreve o contrato para eles; o exemplo de proxy ali não faz parte da implantação
deste serviço.

## Executar localmente

Requisitos: Python 3.12 e Poetry 2.x. Os modelos de OCR são usados localmente pelo
RapidOCR com ONNX Runtime.

```bash
poetry install
poetry run python -m scan_hardware
```

Abra [http://127.0.0.1:8000/demo](http://127.0.0.1:8000/demo) para enviar uma foto
ou digitar um código. A documentação interativa da API fica em `/docs`.
Os [preços em R$](docs/precos.md) podem ser importados de ofertas revisadas e recentes;
o JSON inclui valor, quantidade de lojas e data quando há dados suficientes.
O mesmo guia explica os preços de referência em USD/EUR para alguns modelos antigos,
separados das ofertas atuais em reais.
`GET /health` verifica o processo; `GET /ready` responde HTTP 200 com a contagem de
itens quando o catálogo pode ser pesquisado e HTTP 503 quando está vazio.

Sem importação, o banco padrão é `data/catalog.sqlite3`. Depois de uma importação
validada, o serviço lê `data/latest.json` e usa o banco versionado indicado ali.
`CATALOG_PATH` pode substituir esse caminho. Consulte `.env.example` para as demais
opções. O diretório `data/` não vai para o GitHub.

## Importar o catálogo

Baixe os arquivos completos do Kaggle: [PC Parts by Type](https://www.kaggle.com/datasets/rohitmit98/pc-parts-by-type)
e [PC Parts](https://www.kaggle.com/datasets/warcoder/pc-parts). Salve-os como:

- `data/raw/kaggle/pc-parts-by-type.zip`
- `data/raw/kaggle/warcoder-pc-parts.zip`

Execute:

```bash
poetry run python -m scan_hardware.catalog_import \
  --rohit data/raw/kaggle/pc-parts-by-type.zip \
  --warcoder data/raw/kaggle/warcoder-pc-parts.zip
```

No PowerShell, use uma linha só ou a continuação de linha própria dele. O importador
mantém todas as colunas originais em SQLite e registra rejeições com o motivo. Une
registros apenas quando o nome ou código normalizado permite associação segura;
placas de vídeo com o mesmo nome e chipsets diferentes permanecem separadas.
Descarta URLs de imagem que são placeholders. Dois modelos ECS ausentes dos arquivos
Kaggle são acrescentados por `src/scan_hardware/curation/supplemental_items.json`,
com fonte registrada:
`A785GM-M3` e `G41T-MR23`.

Cada importação cria um banco em `data/processed/<run-id>/`. O ponteiro `data/latest.json`
só muda após os controles de quantidade, rejeição e referências de imagem passarem.
O banco anterior permanece disponível. Na importação validada em 11/10/2026, o
catálogo ficou com **12.874 itens**: 899 CPUs, 7.549 GPUs e 4.426 placas-mães.
Os números podem mudar após novas importações.

### Especificações e imagens

`/scan` e `/lookup` devolvem valores simples diretamente em cada elemento de
`matches`. `GET /specs/{id}` inclui `specs` com valor, unidade e estado.
`reported` vem de uma fonte importada; `verified` foi
conferido em documentação identificada; `conflict` indica valores divergentes e
retorna `value: null`. Um campo ausente significa dado indisponível. As linhas e
colunas originais podem ser consultadas em `GET /items/{id}/sources`.

O pacote inclui **6.007 associações novas de imagem** obtidas por cruzamento exato
entre o catálogo e um [dataset público de peças](https://huggingface.co/datasets/Doshiba/pcpartpicker-parts-dataset).
O cruzamento exige nome original, marca e, para GPU, chipset idênticos; imagens
genéricas e casos ambíguos são descartados. Com as URLs anteriores e as duas ECS, 10.667 dos
12.874 itens (82,8%) têm uma imagem de referência. O arquivo bruto não vai para o
Git; o manifesto resultante vai em `src/scan_hardware/curation/external_images.json`.
Para refazer a coleta com a versão fixa da fonte:

```bash
poetry run python -m scan_hardware.image_enrichment --publish-package
```

O comando baixa o JSONL uma vez para `data/raw/huggingface/`, verifica o SHA-256,
grava manifesto e relatório versionados em `data/processed/images/` e só então
atualiza o arquivo empacotado se passar no portão de cobertura. Veja os
[critérios e limites da coleta](docs/image_enrichment.md).

Também há uma [galeria local por peça](docs/imagens_locais.md), com frente, lado,
verso e detalhe. O Docker Compose guarda catálogo e fotos no volume persistente
`scanner_data`; no início, importa as fotos declaradas em
`data/import/images/manifest.json` e registra o progresso. A galeria é consultada
por `GET /items/{id}/images`. Fotos externas anteriores continuam como referência
quando não há uma foto principal local revisada.

As [especificações complementares](docs/especificacoes_complementares.md) usam
associação exata de fabricante e part number com uma revisão fixa do BuildCores
OpenDB. Isso acrescentou 7.025 valores sem substituir fatos já presentes no
catálogo. A cobertura dos campos principais ainda varia bastante por categoria;
campos sem fonte permanecem vazios.

Cinco itens têm fotos do Wikimedia Commons com autoria e licença revisadas em
`image_attribution`. A GA-Z77X-UD5H usa uma imagem oficial do fabricante. As outras
URLs são referências externas; uma URL pode deixar de funcionar ou mostrar a
embalagem do produto. Os dois modelos ECS suplementares têm URLs externas
associadas, com licença de reutilização não identificada. A foto enviada ao
scanner não substitui a imagem de referência do catálogo.

## Testar a API

Busque um código já conhecido:

```bash
curl -X POST http://127.0.0.1:8000/lookup \
  -H "Content-Type: application/json" \
  -d '{"text":"A785GM-M3"}'
```

Envie uma foto do identificador impresso:

```bash
curl -X POST http://127.0.0.1:8000/scan -F "image=@placa.jpg"
```

O resultado contém `status` e `matches`. `matched` significa código
exato; `suggestions` são candidatos parecidos para confirmação humana; `not_found`
significa que não houve candidato suficiente. Uma sugestão **não** é identificação
confirmada. Cada objeto em `matches` traz diretamente `id`, `brand`, `model` e
especificações disponíveis como `socket`, `memory_slots` ou `cores`. O JSON compacto
omite as evidências detalhadas; consulte as linhas originais
em `GET /items/{id}/sources`. Fotos JPEG, PNG e WebP são aceitas até
8.000.000 bytes por padrão e 20 megapixels. O contrato completo e exemplos de
resposta estão no [guia de integração](docs/integracao.md).

`/lookup` aceita um código parcial, por exemplo `bs500`, e retorna candidatos
ordenados por `match_score`. Use `limit` (1 a 100, padrão 20) e `offset` para
percorrer `total_matches`; a pontuação serve para ordenar, não confirma o modelo.

Quando a cor não consta no catálogo, `/scan` pode estimá-la da foto enviada.
O resultado usa `color_source: "photo_estimate"` para distinguir esse valor de
`color_source: "catalog"`. Uma estimativa prévia da imagem local de referência
aparece como `reference_estimate` também em `/lookup`. A prioridade é catálogo,
foto do scan e referência, nessa ordem. `GET /specs/{id}` continua mostrando as
especificações cadastradas. Um cruzamento por part number com a BuildCores OpenDB
acrescentou 1.487 cores informadas pela fonte; 1.710 modelos ainda dependem de
fotografias confiáveis. Veja o [guia de cores](docs/color_enrichment.md), incluindo
a atribuição e a licença dos dados adicionais.

Para obter os detalhes ou atualizar um item, use `GET /specs/{id}` e `PUT /items/{id}`. Para
associar uma imagem local, use `PUT /items/{id}/image` com o campo multipart `image`;
para baixá-la, use `GET /items/{id}/image`. IDs aceitam letras, dígitos, `_` e `-`.
As gravações são destinadas à administração do catálogo.

## Docker e proteção da API

O Compose sobe PostgreSQL e o scanner. Na primeira inicialização, importa os dois ZIPs
para um SQLite versionado e migra as cinco tabelas normalizadas para PostgreSQL,
verificando contagem e conteúdo. Os dois bancos e as fotos ficam em volumes persistentes.
Coloque os arquivos nos caminhos acima, copie `.env.example` para `.env`, defina
`POSTGRES_PASSWORD` e use a mesma senha em `DATABASE_URL`. Depois execute:

```bash
docker compose up --build
```

Abra `http://127.0.0.1:8000/demo`. Para conferir o banco:

```bash
docker compose exec postgres psql -U scanner -d scan_hardware -c "SELECT category, count(*) FROM items GROUP BY category;"
```

O scanner usa PostgreSQL como banco de operação; `scanner_data` guarda o SQLite de
origem e as fotos. `postgres_data` guarda o banco PostgreSQL. Um SQLite de origem
diferente do já migrado exige uma migração planejada: o serviço interrompe a
inicialização em vez de misturar versões. Consulte o
[guia de migração](docs/postgresql.md).

A porta é publicada em `127.0.0.1:8000`, apenas na máquina local. Se faltar arquivo
ou o catálogo estiver vazio, o início falha. Para uma implantação acessível a outro
serviço, configure `REQUIRE_API_KEY=true` e `API_KEY` aleatória de pelo menos
32 caracteres. Clientes autorizados enviam `X-API-Key`. Mantenha a chave no servidor,
nunca no aplicativo distribuído. Use HTTPS e um proxy apropriado quando o celular
precisar acessar o scanner fora desta máquina.

## Validar e acompanhar qualidade

```bash
poetry run ruff format --check .
poetry run ruff check .
poetry run mypy src/
poetry run pytest -q
poetry run detect-secrets scan
poetry run python -m scan_hardware.catalog_audit
```

Os testes automatizados não fazem chamadas à internet. A suíte de fotos reais usa
um manifesto e imagens guardados localmente fora do Git. Veja a
[validação de campo](docs/field_validation.md), o
[manifesto de exemplo](docs/photo_manifest.example.json) e a
[avaliação das fontes](docs/catalog_sources.md). Para repetir a suíte, salve as fotos
referenciadas pelo manifesto sob `data/validation/` e execute
`poetry run python -m scan_hardware.photo_validation --manifest caminho/manifest.json`.
O relatório vai para uma pasta versionada em `data/validation/`.

Ainda são necessários mais testes com fotos de celular, modelos antigos e revisões
parecidas antes de afirmar uma taxa geral de acerto. A disponibilidade e o direito
de uso das imagens externas também exigem revisão item por item.
