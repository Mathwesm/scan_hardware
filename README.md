# Scanner de hardware

Microserviço Python que lê o **modelo ou part number impresso** em uma foto e pesquisa um catálogo local. Também aceita pesquisa por texto. A API devolve candidatos com campos planos para o aplicativo; a página `/demo` serve para testar. A foto de referência vem do catálogo e pode estar ausente.

## Instalação com pip

Requer Python **3.12 ou superior**. Os comandos abaixo criam um ambiente isolado e instalam as dependências declaradas em `pyproject.toml`.

**Ubuntu 24.04+ e Debian 13+:**

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip libgl1 libglib2.0-0t64 libgomp1
git clone https://github.com/Mathwesm/scan_hardware.git
cd scan_hardware
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
```

**Fedora 44 (Python 3.12):**

```bash
sudo dnf install -y git python3.12 python3-pip mesa-libGL glib2 libgomp
git clone https://github.com/Mathwesm/scan_hardware.git
cd scan_hardware
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
```

**RHEL 9.4+:**

```bash
sudo dnf install -y git python3.12 python3.12-pip mesa-libGL glib2 libgomp
git clone https://github.com/Mathwesm/scan_hardware.git
cd scan_hardware
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
```

Confira `python --version` antes da instalação. Debian 12 e Ubuntu 22.04 trazem um Python padrão anterior a 3.12; instale Python 3.12 separadamente ou use Docker. No Windows, use `.venv\Scripts\Activate.ps1` para ativar o ambiente. O repositório também possui `poetry.lock` para desenvolvimento e CI.

## Importar a base

Baixe os dois datasets do Kaggle: [PC Parts by Type](https://www.kaggle.com/datasets/rohitmit98/pc-parts-by-type) e [PC Parts](https://www.kaggle.com/datasets/warcoder/pc-parts). Salve os ZIPs com estes nomes:

```text
data/raw/kaggle/pc-parts-by-type.zip
data/raw/kaggle/warcoder-pc-parts.zip
```

Com o ambiente ativado, execute na raiz do repositório:

```bash
python -m scan_hardware.catalog_import \
  --rohit data/raw/kaggle/pc-parts-by-type.zip \
  --warcoder data/raw/kaggle/warcoder-pc-parts.zip
python -m scan_hardware.catalog_audit
```

A importação cria `data/processed/<execução>/catalog.sqlite3` e atualiza `data/latest.json` **apenas após validação**. O serviço usa esse catálogo automaticamente. Uma nova importação preserva a versão anterior.

## Rodar e testar

```bash
python -m scan_hardware
```

Abra [http://127.0.0.1:8000/demo](http://127.0.0.1:8000/demo). A API interativa fica em `/docs`; `/ready` verifica se o catálogo está disponível.
O app pode consultar `GET /ready` antes de enviar uma foto: HTTP 200 significa
catálogo pronto, HTTP 503 indica catálogo vazio. `GET /` devolve a mesma
verificação para quem abrir o endereço básico no navegador.

```bash
curl -X POST http://127.0.0.1:8000/lookup \
  -H 'Content-Type: application/json' \
  -d '{"text":"GA-Z77X-UD5H"}'
curl -X POST http://127.0.0.1:8000/scan -F 'image=@placa.jpg'
```

`POST /lookup` pesquisa texto; `POST /scan` lê uma foto. `GET /specs/{id}` traz os detalhes. `GET /specs/{id}/socket-related` lista peças com **o mesmo socket**, com paginação por `limit` e `offset`. A lista exclui divergências conhecidas entre fabricante, chipset e gerações Intel LGA1151 (séries 100/200 versus 300). Ainda é uma lista de candidatos: BIOS e suporte de cada modelo precisam ser conferidos na lista de CPUs do fabricante da placa. O formato JSON da rota permanece o mesmo. O [contrato completo da API](docs/integracao.md) descreve respostas e códigos de erro.

Para abas de catálogo no aplicativo, use `GET /catalog/motherboard`,
`GET /catalog/ram`, `GET /catalog/cpu` e `GET /catalog/gpu`. Cada rota devolve
`total`, `limit`, `offset` e uma lista `items` com os campos da peça em formato
plano. Use `?limit=20&offset=20` para carregar a próxima página. A busca por
código continua em `POST /lookup`, e a câmera continua em `POST /scan`.

## Fotos e especificações adicionais

O pacote já traz associações de fotos do catálogo público PCPartPicker. Para procurar placas-mãe ainda sem foto em mídias com licença aberta, use a API do Openverse:

```bash
python -m scan_hardware.image_discovery --limit 20
```

O comando respeita intervalo entre chamadas e grava `manifest.json` e `report.json` em `data/processed/image-discovery/ID_DA_EXECUCAO/`. Use `--offset 20`, `--offset 40` etc. para percorrer os lotes. A seleção exige marca e modelo exatos, tamanho mínimo, licença e resultado único. **Confira visualmente** os candidatos do relatório; ponha um ID aprovado por linha em `data/approved-images.txt` e publique a execução salva com `--review-run data/processed/image-discovery/ID_DA_EXECUCAO --approved-ids data/approved-images.txt --publish-package`. Reinicie a API. Modelos sem resultado confiável continuam sem foto. [Critérios das imagens](docs/image_enrichment.md).

Para uma busca com maior cobertura, crie uma [conta gratuita de Channel Partner no Open Icecat](https://icecat.biz/en/registration), defina `ICECAT_SHOPNAME` no `.env` e execute `python -m scan_hardware.image_discovery --provider icecat --limit 20`. A conta pública de demonstração não serve para publicar imagens. Revise e publique com o mesmo fluxo acima. Ao mostrar uma imagem Icecat no aplicativo, exiba o crédito **Specs Icecat** e o aviso de conteúdo sem garantias; a página `/demo` já faz isso. A API mantém os mesmos campos.

Dados complementares de CPU, GPU e placa-mãe podem ser reimportados do [BuildCores OpenDB](docs/especificacoes_complementares.md); a fonte fica fora do Git. Campos ausentes ou conflitantes não são inventados. O [relatório de qualidade](docs/field_validation.md) mostra cobertura e limites dos dados.

## Docker com PostgreSQL

Copie `.env.example` para `.env`. Defina `POSTGRES_PASSWORD`; em `DATABASE_URL`, use o usuário `scanner`, host `postgres`, banco `scan_hardware` e a mesma senha. Coloque os ZIPs nos caminhos acima e execute:

```bash
docker compose up --build -d
docker compose ps
docker compose logs -f scan_hardware
```

Na primeira inicialização, o serviço importa o catálogo e o migra para PostgreSQL. Os dados e imagens locais ficam em volumes persistentes. A porta 8000 é exposta apenas em `127.0.0.1`. Veja [implantação e migração](docs/postgresql.md) para servidor físico e [imagens locais](docs/imagens_locais.md) para carregar uma galeria.

## Desenvolvimento

```bash
poetry install
poetry run ruff check .
poetry run mypy src/
poetry run pytest -q
poetry run detect-secrets scan
```

As fotos de teste reais e os ZIPs Kaggle não entram no Git. A [validação por fotografias](docs/field_validation.md) explica como reproduzir os testes de OCR com arquivos locais.
