# Cor das peças e estimativas visuais

O catálogo usa primeiro a cor informada nas bases, incluindo a fonte adicional
[BuildCores OpenDB](https://github.com/buildcores/buildcores-open-db), ou conferida
manualmente. Para
placas-mães e GPUs sem esse valor, `/scan` pode estimar uma cor da foto enviada.
`color_source: "photo_estimate"` sinaliza essa aproximação. A foto pode mostrar
apenas um slot, dissipador ou embalagem; por isso a estimativa não é gravada como
especificação verificada.

Para uma busca por texto (`/lookup`), o serviço pode usar uma estimativa calculada
antes a partir de uma **foto local associada ao ID exato do item**. Nesse caso,
`color_source` vale `reference_estimate`. Se houver cor no catálogo, ela vence
as duas estimativas e `color_source` vale `catalog`. CPU não recebe estimativa
de cor, pois o campo descreve mal o processador e sua embalagem.

## Processar fotos locais em lote

Crie um JSON em `data/color_images.json`, por exemplo:

```json
{
  "images": [
    {"item_id": "motherboard-ecs-a785gm-m3-v1", "path": "photos/a785gm-m3.webp"},
    {"item_id": "motherboard-ecs-g41t-mr23-v1", "path": "photos/g41t-mr23.jpg"}
  ]
}
```

Os caminhos das fotos são relativos ao arquivo JSON. Execute:

```bash
poetry run python -m scan_hardware.color_batch --manifest data/color_images.json --publish-package
```

O comando gera um manifesto e relatório imutáveis em `data/processed/colors/`.
Quando `--publish-package` é usado, o resultado é incorporado a
`src/scan_hardware/curation/estimated_colors.json` e a versão anterior fica
na pasta da execução. Reinicie o serviço após publicar. Fotos ausentes, inválidas,
com cor incerta ou conflitantes entre si são rejeitadas com contagem por motivo.
O arquivo publicado contém apenas ID, modelo, categoria e cor estimada;
as fotos permanecem fora do Git.

O manifesto incluído hoje cobre as **duas ECS** testadas. A maior parte dos
modelos sem cor ainda não tem uma foto local processada. Mesmo com imagem, uma
foto com iluminação ruim ou vários produtos pode ficar sem estimativa. O
processamento em lote não baixa imagens de sites externos.

## Cores informadas pela BuildCores

Uma cópia local da revisão `0d3c3eaf220173aa4246916e3d7a226079e87a65`
da OpenDB foi cruzada por **part number exato e fabricante**. O importador
descarta códigos ambíguos, cores inválidas e itens que já têm cor nas bases
Kaggle. A execução publicada acrescentou **1.487 cores**: 1.412 GPUs e 75
placas-mães. Essas cores aparecem como `color_source: "catalog"` em `/scan` e
`/lookup`, e como especificação `reported` em `GET /specs/{id}`.

Para reproduzir a coleta a partir da revisão fixa:

```bash
git clone --depth 1 --filter=blob:none --sparse https://github.com/buildcores/buildcores-open-db.git data/raw/buildcores-open-db
git -C data/raw/buildcores-open-db fetch --depth 1 origin 0d3c3eaf220173aa4246916e3d7a226079e87a65
git -C data/raw/buildcores-open-db checkout --detach 0d3c3eaf220173aa4246916e3d7a226079e87a65
git -C data/raw/buildcores-open-db sparse-checkout set open-db/GPU open-db/Motherboard
poetry run python -m scan_hardware.reported_color_import --source-root data/raw/buildcores-open-db --publish-package
```

O comando exige a revisão indicada, salva relatório e manifesto versionados em
`data/processed/colors/buildcores/` e preserva a versão anterior antes de publicar.
O arquivo [reported_colors.json](../src/scan_hardware/curation/reported_colors.json)
é uma adaptação de dados [CC BY-NC-SA 4.0](https://github.com/buildcores/buildcores-open-db/blob/main/LICENSE.txt):
crédito a BuildCores OpenDB, revisão fixada acima; modificação feita aqui:
seleção por código exato e normalização dos nomes de cor. Fotos e logos de
terceiros não fazem parte dessa licença nem deste arquivo.

Na auditoria de 12/10/2026, 438 placas-mães e 1.274 GPUs ainda não tinham
cor única no catálogo. Dessas 1.712 peças, duas têm a estimativa local das ECS;
**1.710 continuam sem cor**. Cores iguais em ordem diferente, como
`Black / Silver` e `Silver / Black`, são tratadas como equivalentes.
