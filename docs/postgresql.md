# PostgreSQL local e migração do catálogo

## Subir no Docker

1. Coloque os dois ZIPs Kaggle em `data/raw/kaggle/` com os nomes indicados no README.
2. Copie `.env.example` para `.env`. Defina uma senha privada, sem caracteres que
   precisem de codificação em URL, em `POSTGRES_PASSWORD` e repita-a em
   `DATABASE_URL` como URL PostgreSQL para o usuário `scanner`, host `postgres`,
   porta `5432` e banco `scan_hardware`, incluindo a mesma senha.
3. Execute `docker compose up --build` e abra `http://127.0.0.1:8000/demo`.

O container `postgres` não publica a porta 5432 na máquina. O scanner o acessa pelo
nome `postgres` na rede do Compose. O volume `postgres_data` persiste as tabelas; o
volume `scanner_data` mantém o SQLite importado e as fotos. Não use
`docker compose down -v` se quiser conservar esses dados.

Na primeira execução, o importador cria um SQLite versionado. A migração transfere,
em uma transação, `items`, `identifiers`, `source_records`, `item_images` e
`price_observations`, nessa ordem. Chaves primárias, estrangeiras e índices são
criados antes da cópia. A migração compara a quantidade e um SHA-256 dos registros
ordenados em cada tabela. Se divergir, a transação é revertida e o scanner não sobe.
Ela registra a versão importada em `catalog_imports`; reinícios com a mesma versão
não duplicam registros. Ao atualizar uma instalação antiga sem RAM, o scanner
recria um SQLite versionado a partir dos ZIPs, compara os registros anteriores
de CPU, GPU e placa-mãe e acrescenta apenas RAM ao PostgreSQL em uma transação.
Fotos e preços já gravados permanecem. Qualquer alteração nos registros anteriores
interrompe a atualização sem trocar o banco; outras versões diferentes exigem
revisão manual. O SQLite anterior continua no volume para comparação ou retorno.
Fotos e ofertas de manifestos
são importadas **depois** da migração, diretamente no PostgreSQL.

## Verificar

```bash
docker compose ps
docker compose exec postgres psql -U scanner -d scan_hardware -c "SELECT category, count(*) FROM items GROUP BY category;"
docker compose exec postgres psql -U scanner -d scan_hardware -c "SELECT count(*) FROM source_records;"
```

`GET /ready` deve responder 200 e a contagem de itens. O aplicativo usa PostgreSQL
quando `DATABASE_URL` está definida. Sem ela, a execução direta com Poetry continua
usando SQLite para desenvolvimento e ferramentas de importação locais.

## Servidor Linux futuro

Instale Docker Engine e o plugin Compose, copie este repositório e os ZIPs para o
servidor, crie `.env` localmente e execute `docker compose up -d --build`. Publique
o scanner por HTTPS atrás de um proxy e configure `REQUIRE_API_KEY=true` com uma
`API_KEY` de pelo menos 32 caracteres. O banco deve continuar acessível só pela
rede interna do Compose. Guarde backup de **ambos** os volumes: `postgres_data`
para tabelas e `scanner_data` para fotos e o SQLite de origem. Para exportar as
tabelas em SQL em um shell Linux:

```bash
docker compose exec -T postgres pg_dump -U scanner -d scan_hardware > scan_hardware.sql
```

Teste uma restauração em um banco separado antes de depender do backup. O endereço
SSH e a distribuição do servidor ainda não foram fornecidos, então a instalação
remota não pode ser validada agora.
