# Integração do microserviço Hardware Scanner

Este guia é para quem vai criar o aplicativo móvel ou o backend que o atende. O scanner
roda separadamente em Python, guarda o catálogo em SQLite e expõe uma API HTTP. Ele lê
**identificadores impressos** com OCR e procura esses códigos no catálogo. Ele não
classifica a aparência da placa inteira.

## Fluxo recomendado

```text
Celular → backend do aplicativo (HTTPS) → Hardware Scanner → catálogo local
        ← resultado, especificações e imagem de referência ←
```

O celular fotografa **uma peça por vez**, com o modelo ou part number legível. O backend
recebe a foto, aplica sua autenticação de usuário e a encaminha para `POST /scan`. Se o
app já leu o código por conta própria, envia o texto para `POST /lookup`. O backend
guarda `X-API-Key` no servidor; nunca a inclua no aplicativo distribuído. Para exibir
uma imagem local protegida, o backend também deve encaminhar o download.

## Subir e verificar

Na pasta deste repositório, com Python 3.12 e Poetry 2.x:

```bash
poetry install
poetry run python -m scan_hardware
```

O servidor local escuta em `http://127.0.0.1:8000`. Abra `/demo` para um teste manual
e `/docs` para o OpenAPI interativo. Antes de integrar, confira:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
```

`/health` responde `{"status":"ok"}` quando o processo está no ar. `/ready` responde
`{"status":"ready","items":N}` com HTTP 200 quando existe um catálogo pesquisável;
responde HTTP 503 se estiver vazio. O primeiro carregamento dos dois arquivos Kaggle
está explicado no [README](../README.md#import-the-kaggle-catalog). Sem importação,
o serviço pode subir, mas não encontra produtos.

O `compose.yaml` aceita os ZIPs em `data/raw/kaggle/` e persiste o catálogo num volume.
Seu mapeamento de porta é `127.0.0.1:8000:8000`: o celular não acessa essa porta
diretamente. Em outro servidor, use rede privada ou um proxy HTTPS e ajuste a
publicação de portas à infraestrutura escolhida.

### Configuração de integração

Copie `.env.example` para `.env` e, em um ambiente acessível pelo backend, configure:

```dotenv
REQUIRE_CATALOG=true
REQUIRE_API_KEY=true
API_KEY=<valor_aleatorio_com_pelo_menos_32_caracteres>
```

Essas variáveis também podem ser passadas pelo ambiente. O Docker Compose já repassa
`REQUIRE_API_KEY` e `API_KEY`, mas, por padrão, deixa a autenticação desligada para
testes locais. Quando ligada, **todas** as rotas exceto `/health` e `/ready` exigem o
header `X-API-Key`, inclusive `/docs`, `/demo` e o download de imagens. Chave ausente
ou incorreta resulta em HTTP 401. Mantenha a chave no backend ou no gerenciador de
segredos da implantação.

## Contrato HTTP

| Rota | Entrada | Uso |
| --- | --- | --- |
| `POST /scan` | `multipart/form-data`, campo `image` | OCR da foto e busca no catálogo. |
| `POST /lookup` | JSON `{"text":"A890GXM-A"}` | Busca de código já digitado ou lido pelo app. |
| `GET /items/{id}` | ID recebido na resposta | Detalhes atuais do produto. |
| `GET /items/{id}/sources` | ID recebido na resposta | Linhas originais das fontes, com todas as colunas importadas. |
| `GET /items/{id}/image` | ID com imagem local | Arquivo da imagem de referência. |
| `PUT /items/{id}` | JSON do produto | Cria ou substitui um item do catálogo. |
| `PUT /items/{id}/image` | `multipart/form-data`, campo `image` | Associa uma imagem local a um item existente. |

`/scan` e `/lookup` devolvem o mesmo formato. Em produção, as rotas `PUT` devem ser
usadas apenas por processos administrativos autorizados. Os IDs em `/{id}` aceitam
letras, dígitos, `_` e `-`, de 1 a 64 caracteres. O upload aceita JPEG, PNG ou WebP,
com até **8.000.000 bytes** por padrão e **20 megapixels**. O limite de bytes pode ser
alterado por `MAX_UPLOAD_BYTES`.

Exemplos, com a autenticação desligada no teste local:

```bash
curl -X POST http://127.0.0.1:8000/scan -F "image=@placa.jpg"
curl -X POST http://127.0.0.1:8000/lookup \
  -H "Content-Type: application/json" \
  -d '{"text":"A890GXM-A"}'
```

No PowerShell, execute cada comando em uma linha ou use a continuação de linha do
PowerShell. Com a autenticação ligada, acrescente `-H "X-API-Key: <sua-chave>"`.

### Interpretar a resposta

```json
{
  "status": "matched",
  "detected_text": ["A890GXM-A V:1.0"],
  "matches": [
    {
      "item": {
        "category": "motherboard",
        "brand": "ECS",
        "model": "ECS A890GXM-A",
        "identifiers": ["A890GXM-A", "ECS A890GXM-A"],
        "image_url": "https://example.org/reference.jpg",
        "id": "motherboard-example",
        "has_local_image": false,
        "local_image_url": null,
        "image_attribution": null,
        "specifications": {
          "socket": {
            "value": "AM3",
            "unit": null,
            "status": "reported",
            "evidence": [
              {
                "dataset": "warcoder/pc-parts",
                "field": "socket",
                "value": "AM3",
                "source_url": null
              }
            ]
          }
        }
      },
      "matched_identifier": "A890GXM-A",
      "observed_text": "A890GXM-A V:1.0",
      "score": 1.0,
      "is_exact": true
    }
  ]
}
```

O exemplo acima ilustra o **formato**; ID, imagem e evidências concretas dependem da
versão do catálogo. `category` é `motherboard`, `gpu` ou `cpu`.

| `status` | Significado | Ação no aplicativo |
| --- | --- | --- |
| `matched` | Pelo menos um identificador bateu exatamente. | Mostrar os itens e o texto que justificou a correspondência. Se houver mais de um, pedir escolha. |
| `suggestions` | Há candidatos parecidos, sem confirmação exata. | Mostrar como sugestões e pedir confirmação humana. Nunca chamar de identificação confirmada. |
| `not_found` | Nenhum candidato suficiente. | Exibir `detected_text`, permitir corrigir o código ou tirar outra foto. |

`matches` pode estar vazio. `score` vai de 0 a 1, mas **não é uma probabilidade
calibrada**. Use `is_exact` e `status` para a decisão principal. O serviço pode
retornar até cinco itens; numa foto que contém várias peças, um item encontrado pode
ocultar sugestões de outros códigos. Peça uma foto por peça.

Em `specifications`, cada campo traz `value`, `unit`, `status` e `evidence`:

- `verified`: valor conferido em uma fonte específica, com URL de evidência.
- `reported`: valor presente na base importada, ainda não verificado diretamente.
- `conflict`: fontes discordam; `value` é `null`. Mostre as evidências e não escolha um
  valor por conta própria.

Campo ausente significa dado indisponível, não valor zero. Isso importa em CPU:
frequência, núcleos, threads e socket podem faltar em alguns registros.

Para a foto de referência, prefira `local_image_url` quando não for `null`, compondo
com a URL base do scanner **no backend**. Caso contrário, `image_url` pode apontar a
um host externo e pode estar indisponível ou sem direitos de exibição comprovados.
Se houver `image_attribution`, mostre criador, fonte e licença. Se não houver imagem
adequada, exiba um estado "sem imagem"; não use a foto enviada como se fosse a foto
de referência do catálogo.

### Erros que o cliente deve tratar

| HTTP | Situação típica | Ação |
| --- | --- | --- |
| 401 | `X-API-Key` ausente/incorreta. | Verificar a configuração do backend; não pedir a chave ao usuário. |
| 404 | Item ou imagem local inexistente. | Atualizar a consulta ou mostrar "sem imagem". |
| 409 | Identificador já associado a outro item em `PUT /items/{id}`. | Resolver conflito de catálogo antes de repetir a gravação. |
| 422 | Imagem vazia, inválida, formato/tamanho acima do limite ou payload inválido. | Pedir outra foto ou corrigir o envio. |
| 503 | `/ready` sem catálogo. | Não iniciar o fluxo de busca; corrigir a importação. |

Timeout ou falha de rede não significam `not_found`: mostre erro temporário e permita
tentar de novo. Não faça retry automático de uma imagem inválida (HTTP 422).

## Exemplo de backend intermediário em Python

Este exemplo usa FastAPI e httpx no **backend do aplicativo**. Configure
`SCANNER_URL` com um endereço alcançável **desse backend** e `SCANNER_API_KEY` com
a chave do microserviço. Instale as dependências conforme a convenção do projeto do
backend. A autenticação dos usuários do aplicativo entra antes dessas rotas.

```python
import os

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

app = FastAPI()
scanner_url = os.environ["SCANNER_URL"].rstrip("/")
scanner_key = os.environ["SCANNER_API_KEY"]
headers = {"X-API-Key": scanner_key}


class LookupBody(BaseModel):
    text: str = Field(min_length=1, max_length=500)


async def call_scanner(path: str, **kwargs: object) -> httpx.Response:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
            return await client.request(
                kwargs.pop("method", "POST"),
                f"{scanner_url}{path}",
                headers=headers,
                **kwargs,
            )
    except httpx.RequestError as error:
        raise HTTPException(status_code=502, detail="Scanner unavailable") from error


@app.post("/hardware/scan")
async def scan(image: UploadFile = File()) -> JSONResponse:
    content = await image.read(8_000_001)
    if len(content) > 8_000_000:
        raise HTTPException(status_code=413, detail="Image too large")
    response = await call_scanner(
        "/scan",
        files={"image": (image.filename or "photo.jpg", content, image.content_type)},
    )
    return JSONResponse(status_code=response.status_code, content=response.json())


@app.post("/hardware/lookup")
async def lookup(body: LookupBody) -> JSONResponse:
    response = await call_scanner("/lookup", json=body.model_dump())
    return JSONResponse(status_code=response.status_code, content=response.json())


@app.get("/hardware/items/{item_id}/image")
async def reference_image(item_id: str) -> Response:
    response = await call_scanner(f"/items/{item_id}/image", method="GET")
    return Response(
        content=response.content,
        status_code=response.status_code,
        media_type=response.headers.get("content-type"),
    )
```

Neste exemplo, use no backend `SCANNER_URL=http://127.0.0.1:8000` somente quando
os dois processos rodarem na **mesma máquina**. Dentro do Compose, um serviço na
mesma rede usaria o nome `scan_hardware` e a porta 8000. Em máquinas diferentes,
configure um endereço privado ou HTTPS alcançável pelo backend. O exemplo limita a
leitura do upload, mas a implantação ainda deve limitar requisições no proxy e
controlar quem pode chamar suas rotas.

## Exemplo mínimo do lado do celular

Em um app web ou protótipo móvel, um campo de arquivo pode abrir a câmera traseira:

```html
<input id="photo" type="file" accept="image/jpeg,image/png,image/webp" capture="environment">
<button id="search">Identificar</button>
<script>
  document.querySelector("#search").addEventListener("click", async () => {
    const file = document.querySelector("#photo").files[0];
    if (!file) return;
    const form = new FormData();
    form.append("image", file);
    const response = await fetch("/hardware/scan", { method: "POST", body: form });
    const result = await response.json();
    if (!response.ok) {
      // Show a network or validation error to the user.
      return;
    }
    // Render result.status, result.detected_text and result.matches.
    // Confirm suggestions with the user before accepting an item.
  });
</script>
```

O `capture` é apenas uma dica ao navegador; confirme o comportamento no Android e
no iOS usados pelo aplicativo. Não defina manualmente `Content-Type` ao enviar
`FormData`: o navegador inclui o boundary correto. Em app nativo, o contrato HTTP é
o mesmo. Adapte o caminho `/hardware/scan` ao backend que você criar.

## Limites já observados

Na foto de teste com três placas, o OCR leu `A785GM-M3`, `G41T-MR23` e
`A890GXM-A`. A base atual confirmou exatamente apenas `A890GXM-A`. Os outros
códigos precisam ser incluídos e validados no catálogo; `A785GM-M` apareceu só
como sugestão para `A785GM-M3` e **não** é a mesma identificação. Veja os demais
ensaios em [validação de campo](field_validation.md).

Antes de publicar o aplicativo, valide fotos reais de cada categoria, com iluminação,
foco e modelos variados. O catálogo tem lacunas de especificações e imagens; a
presença de uma URL externa não confirma licença de uso nem disponibilidade futura.
