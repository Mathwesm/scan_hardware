# Galeria de imagens no servidor físico

O serviço armazena fotos localmente em `data/images/` e os vínculos com as peças
no PostgreSQL. No Docker Compose, as fotos ficam em `scanner_data` e os vínculos
em `postgres_data`.
Recriar o contêiner preserva as imagens; remover o volume apaga esse acervo.
Não é necessário um serviço de bucket separado.

## Preparar fotos para importação

Coloque os arquivos em `data/import/images/` junto com `manifest.json`:

```json
{
  "images": [
    {"item_id": "motherboard-2716c8c323f0e5902e139112", "path": "placa-frente.jpg", "view": "front"},
    {"item_id": "motherboard-2716c8c323f0e5902e139112", "path": "placa-verso.jpg", "view": "back"},
    {"item_id": "motherboard-2716c8c323f0e5902e139112", "path": "placa-detalhe.jpg", "view": "detail"}
  ]
}
```

Os valores de `view` são `front`, `side`, `back`, `detail` e `other`. A primeira
foto `front` vira principal, salvo se `is_primary` for `false`. As demais são
secundárias. A foto principal precisa ter pelo menos 800 pixels em cada lado.
Em fundo uniforme, o enquadramento é rejeitado se a peça ocupar menos de 25%
da área. Esse filtro automático não confirma que o modelo da foto esteja correto:
quem preenche o manifesto deve conferir a inscrição e o código da peça.

Inicie com `docker compose up --build`. O serviço importa o catálogo Kaggle na
primeira execução e depois lê o manifesto de imagens. Os logs mostram uma barra
de progresso e um relatório de importação versionado em
`data/processed/image-import/` dentro do volume. A importação pode ser repetida:
arquivos idênticos conservam o mesmo hash e não criam cópias extras.
Um registro ruim é rejeitado com motivo; se todos forem rejeitados, o comando
falha. Para importar manualmente no ambiente Poetry:

```bash
poetry run python -m scan_hardware.image_seed --manifest data/import/images/manifest.json
```

Os arquivos em `data/` ficam fora do Git. Para migrar ao servidor físico, copie
os ZIPs Kaggle e a pasta `data/import/images/`; faça backup do volume Docker
depois da importação. Se o manifesto não estiver presente, o serviço continua
com as URLs externas já cadastradas.

## Enviar fotos pela API

```bash
curl -X PUT "http://127.0.0.1:8000/items/ID/images/front" -F "image=@frente.jpg"
curl -X PUT "http://127.0.0.1:8000/items/ID/images/back" -F "image=@verso.jpg"
curl "http://127.0.0.1:8000/items/ID/images"
```

O JSON da galeria contém `url`, `view`, `is_primary`, `source`, `width` e
`height`. `source=external` sinaliza uma referência anterior cujo enquadramento
não passou pela revisão local. A rota antiga `PUT /items/{id}/image` continua
disponível para clientes existentes. O campo `image_url` de `/scan` e `/lookup`
aponta para a imagem principal quando ela existe.

Não faça download em massa de páginas ou imagens sem verificar as regras da
fonte. Guarde a origem e os direitos de uso de cada foto no seu processo de
curadoria. A galeria local oferece armazenamento e apresentação; a maioria dos
12.874 produtos ainda não tem fotos locais em vários ângulos.
