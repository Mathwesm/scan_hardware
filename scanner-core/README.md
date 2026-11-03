# Hardware Scan Core

Scanner mínimo e independente. Recebe bytes de uma foto, lê texto impresso com
RapidOCR e procura códigos de modelo em um catálogo JSON local. Devolve texto
detectado e itens encontrados com suas especificações. Não precisa de servidor,
PostgreSQL, Docker ou internet durante o scan.

## Instalação

Requer Python 3.12 e Poetry:

```powershell
poetry install
```

## Teste com uma foto

O arquivo `catalog.example.json` contém cinco exemplos. A foto de teste contém
três códigos ECS que estão nesse catálogo:

```powershell
poetry run hardware-scan tests/fixtures/placa.jpg --catalog catalog.example.json
```

Esta branch inclui `catalog.json.gz` com os 21.509 itens exportados do catálogo
existente. Assim, o scanner pode consultar as especificações após o clone,
sem precisar executar o servidor principal ou descompactar o arquivo:

```powershell
poetry run hardware-scan tests/fixtures/placa.jpg --catalog catalog.json.gz
```

Para o seu próprio catálogo, crie um JSON com `id`, `category`, `brand`, `model`,
`identifiers` (códigos impressos na peça) e `specs` (campos que você quer devolver).
O retorno contém `detected_text` e `matches`. Uma lista vazia significa que não
houve correspondência exata; a aplicação pode pedir outra foto ou confirmação.

## Uso em outro aplicativo

```python
from pathlib import Path
from hardware_scan import Scanner, load_catalog

catalog = load_catalog(Path("catalog.example.json"))
result = Scanner().scan(photo_bytes, catalog)
payload = result.model_dump(mode="json")
```

O aplicativo do celular abre a câmera e envia os bytes da foto para essa função
ou para um backend que a chame. Este pacote não controla a câmera. O catálogo é
injetado pelo integrador, então ele pode usar os códigos para outra finalidade.

Este projeto fica em `scanner-core/` na branch `feat/minimal-scan-core` do
repositório `scan_hardware`. O catálogo é uma cópia local: alterações feitas
posteriormente no PostgreSQL não aparecem aqui automaticamente. Os campos
ausentes no catálogo permanecem ausentes; `image_url` aponta para uma imagem
externa quando ela está cadastrada. Este exemplo não inclui ranking aproximado,
consulta ao banco de dados, API ou coleta de imagens.

## Validação

```powershell
poetry run ruff check .
poetry run mypy src/
poetry run pytest -q
```
