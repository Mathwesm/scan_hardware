# Integração do microserviço Hardware Scanner

Este guia é para quem vai criar o aplicativo móvel ou o backend que o atende. O scanner
roda separadamente em Python, guarda o catálogo operacional em PostgreSQL no Docker
(ou SQLite na execução local sem `DATABASE_URL`) e expõe uma API HTTP. Ele lê
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

O `compose.yaml` aceita os ZIPs em `data/raw/kaggle/`, cria PostgreSQL e persiste
o catálogo e as fotos em volumes locais. Configure `.env` como no
[guia de migração](postgresql.md).
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
| `GET /specs/{id}` | ID recebido na resposta | Detalhes e especificações do produto. |
| `GET /items/{id}/sources` | ID recebido na resposta | Linhas originais das fontes, com todas as colunas importadas. |
| `GET /items/{id}/image` | ID com imagem local | Arquivo da imagem de referência. |
| `GET /items/{id}/images` | ID recebido na resposta | Galeria com frente, lado, verso e detalhes disponíveis. |
| `GET /items/{id}/images/{arquivo}` | `url` retornada pela galeria | Arquivo de uma foto local. |
| `PUT /items/{id}` | JSON do produto | Cria ou substitui um item do catálogo. |
| `PUT /items/{id}/image` | `multipart/form-data`, campo `image` | Associa uma imagem local a um item existente. |
| `PUT /items/{id}/images/{view}` | `multipart/form-data`, campo `image` | Adiciona uma foto local; `view` aceita `front`, `side`, `back`, `detail`, `other`. |

`/scan` e `/lookup` devolvem o mesmo formato. Em produção, as rotas `PUT` devem ser
usadas apenas por processos administrativos autorizados. Os IDs em `/{id}` aceitam
letras, dígitos, `_` e `-`, de 1 a 64 caracteres. O upload aceita JPEG, PNG ou WebP,
com até **8.000.000 bytes** por padrão e **20 megapixels**. O limite de bytes pode ser
alterado por `MAX_UPLOAD_BYTES`.

Quando houver uma oferta recente, cada candidato de `/scan` e `/lookup`, assim como
`GET /specs/{id}`, inclui `estimated_price_brl` (número em R$),
`price_offer_count` (lojas consideradas) e `price_observed_at` (UTC). Esses campos
são omitidos quando não há oferta válida nos últimos 14 dias. O aplicativo deve
apresentar `price_offer_count=1` como preço observado, pois não é média de mercado.
`price_status` informa `observed`, `average`, `reference_only` ou `unavailable`;
quando está `unavailable`, não há preço a mostrar para aquele modelo exato.
Também pode valer `reference_only` quando há apenas preço histórico ou de dataset.
Nesse caso, use `reference_price_amount` com `reference_price_currency` (USD ou EUR),
`reference_price_context`, `reference_price_source_url` e a data opcional
`reference_price_date`. Essa referência não representa venda atual em R$.
Veja [importação e cálculo dos preços](precos.md).

Para várias fotos da mesma peça, o aplicativo pode buscar
`GET /items/{id}/images` e mostrar a entrada `is_primary=true` primeiro.
As demais podem ser apresentadas como miniaturas. `source=external` identifica
uma URL de referência anterior, sem revisão de enquadramento local. Consulte o
[guia de imagens locais](imagens_locais.md) para o manifesto usado pelo Docker.

Exemplos, com a autenticação desligada no teste local:

```bash
curl -X POST http://127.0.0.1:8000/scan -F "image=@placa.jpg"
curl -X POST http://127.0.0.1:8000/lookup \
  -H "Content-Type: application/json" \
  -d '{"text":"A890GXM-A"}'
curl -X POST http://127.0.0.1:8000/lookup \
  -H "Content-Type: application/json" \
  -d '{"text":"bs500","limit":20,"offset":0}'
```

No PowerShell, execute cada comando em uma linha ou use a continuação de linha do
PowerShell. Com a autenticação ligada, acrescente `-H "X-API-Key: <sua-chave>"`.

### Interpretar a resposta

```json
{
  "status": "matched",
  "matches": [
    {
      "category": "motherboard",
      "brand": "ECS",
      "model": "ECS A890GXM-A",
      "image_url": "https://example.org/reference.jpg",
      "id": "motherboard-example",
      "socket": "AM3",
      "form_factor": "ATX",
      "memory_slots": 4
    }
  ]
}
```

O exemplo acima ilustra o **formato**; ID e imagem dependem da
versão do catálogo. `category` é `motherboard`, `gpu`, `cpu` ou `ram`.

| `status` | Significado | Ação no aplicativo |
| --- | --- | --- |
| `matched` | Pelo menos um identificador bateu exatamente. | Mostrar os itens. Se houver mais de um, pedir escolha. |
| `suggestions` | Há candidatos parecidos, sem confirmação exata. | Mostrar como sugestões e pedir confirmação humana. Nunca chamar de identificação confirmada. |
| `not_found` | Nenhum candidato suficiente. | Permitir corrigir o código ou tirar outra foto. |

Quando o OCR troca `5` por `S` ou `0` por `O` em códigos `B550`, o serviço
considera a leitura corrigida na busca aproximada. Exemplos como `BS5OM-A` e
`PRIME BSSOM-A` podem gerar `suggestions`; a correção nunca transforma a leitura
em `matched`. Em textos incompletos como `TUF GAMING BSSO`, peça confirmação do
modelo completo antes de mostrar uma peça como identificada.

`matches` é sempre uma lista, vazia em `not_found`. `/scan` retorna até cinco
candidatos. `/lookup` aceita texto parcial, inclusive `bs500` como leitura ambígua
de `B550`, e retorna até 20 por página (ou `limit` entre 1 e 100). Envie `offset`
para obter as páginas seguintes e leia `total_matches` para saber quantos existem.
Cada sugestão inclui `match_score` de 0 a 1; é uma pontuação de ordenação, não uma
probabilidade de acerto nem confirmação do modelo. Cada
candidato contém campos simples: texto, número ou booleano. `socket`, `memory_slots`,
`cores`, `threads` e outros campos só aparecem quando há um valor sem conflito.
O sufixo do nome informa a unidade, como `_ghz`, `_gb`, `_mhz`, `_mt_s`, `_mm`, `_mb` ou `_w`.
Campo ausente significa dado indisponível ou conflitante, nunca zero. Use `status`
para distinguir correspondência exata de sugestão. Peça uma foto por peça.
Quando `/scan` não tem cor confiável no catálogo, ele pode preencher `color` a
partir dos pixels da foto. Nesse caso, `color_source` vale `photo_estimate`:
é uma aproximação visual, sujeita a fundo, iluminação, enquadramento e peças
com várias cores. Se a cor vem do catálogo, `color_source` vale `catalog`.
Uma estimativa previamente gerada de uma imagem local da peça usa
`color_source: "reference_estimate"`; ela também aparece em `/lookup` quando
ID, categoria e modelo continuam exatamente iguais. Quando não há base
suficiente, os campos são omitidos. Estimativas não substituem cores documentadas.
O [processamento local de fotos](color_enrichment.md) explica como ampliar a cobertura.
Para memória de placas-mães, `max_memory_gb` é capacidade em GB;
`max_memory_standard_mhz` e `max_memory_oc_mhz` diferenciam o limite sem e com
overclock. `memory_slot_type` indica o encaixe físico (por exemplo, DIMM), e
`memory_channels` indica os canais suportados. Para CPU, `memory_speed_mt_s` é a
taxa máxima oficial de transferências por segundo, distinta do clock em MHz;
`l2_cache_mb` e `l3_cache_mb` indicam o cache. Para GPU, `memory_type` indica a
tecnologia da VRAM, `memory_speed_mhz` sua velocidade anunciada,
`memory_bus_bits` a largura do barramento e `shader_units` as unidades de
processamento quando o fabricante as informa. Esses campos só aparecem para
modelos com fonte identificada; não são deduzidos a partir de outro SKU.
Para RAM, `capacity_gb` é a capacidade total do kit, `module_count` é a quantidade
de módulos e `module_capacity_gb` a capacidade de cada um. `memory_type` informa
a geração DDR, `memory_speed_mt_s` a taxa anunciada e `cas_latency` a latência CAS.
O código de peça impresso permite correspondência exata; nomes de famílias sem
part number não devem ser tratados como confirmação de um kit específico.

O JSON compacto é exclusivo de `/scan` e `/lookup`. Para detalhes, estado de cada
especificação, licença da imagem e todas as colunas das fontes, consulte
`GET /specs/{id}` e `GET /items/{id}/sources`. `image_url` na resposta compacta
prioriza a imagem local; uma URL externa pode estar indisponível ou sem direitos de
exibição comprovados. Uma URL local precisa ser resolvida pelo backend que atende
o celular. Se não houver imagem, o campo é omitido. Na coleta de 12/10/2026,
10.667 de 12.874 itens têm uma referência de imagem; o aplicativo ainda precisa
mostrar um substituto quando `image_url` estiver ausente ou o host externo falhar.

### Modelo simples em Kotlin

```kotlin
import kotlinx.serialization.Serializable

@Serializable
data class ScanResponse(
    val status: String,
    val matches: List<Hardware> = emptyList(),
    val total_matches: Int? = null,
)

@Serializable
data class Hardware(
    val category: String,
    val brand: String,
    val model: String,
    val id: String,
    val match_score: Double? = null,
    val image_url: String? = null,
    val socket: String? = null,
    val form_factor: String? = null,
    val max_memory_gb: Int? = null,
    val memory_slots: Int? = null,
    val memory_type: String? = null,
    val memory_slot_type: String? = null,
    val memory_channels: Int? = null,
    val max_memory_standard_mhz: Int? = null,
    val max_memory_oc_mhz: Int? = null,
    val memory_speed_mt_s: Int? = null,
    val l2_cache_mb: Int? = null,
    val l3_cache_mb: Int? = null,
    val color: String? = null,
    val color_source: String? = null,
    val base_clock_ghz: Double? = null,
    val boost_clock_ghz: Double? = null,
    val cores: Int? = null,
    val threads: Int? = null,
    val tdp_w: Int? = null,
    val integrated_graphics: String? = null,
    val smt: Boolean? = null,
    val chipset: String? = null,
    val vram_gb: Int? = null,
    val memory_speed_mhz: Int? = null,
    val memory_bus_bits: Int? = null,
    val shader_units: Int? = null,
    val core_clock_mhz: Int? = null,
    val boost_clock_mhz: Int? = null,
    val board_power_w: Int? = null,
    val length_mm: Int? = null,
    val resolution_class: String? = null,
)
```

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
    // Render result.status and result.matches.
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
`A890GXM-A`. Após incluir os dois modelos ausentes no catálogo, os três recortes
e a montagem inteira retornaram correspondências exatas. `A785GM-M` continua
sendo um modelo diferente de `A785GM-M3`: não trate prefixos parecidos como o
mesmo produto. Veja os ensaios em [validação de campo](field_validation.md).

Antes de publicar o aplicativo, valide fotos reais de cada categoria, com iluminação,
foco e modelos variados. O catálogo tem lacunas de especificações e imagens; a
presença de uma URL externa não confirma licença de uso nem disponibilidade futura.
