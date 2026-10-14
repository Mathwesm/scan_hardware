# Especificações complementares e cobertura

O catálogo original combina dois arquivos Kaggle e tem **12.874 peças**:
899 CPUs, 7.549 GPUs e 4.426 placas-mães. A importação adicional do
[BuildCores OpenDB](https://github.com/buildcores/buildcores-open-db), na revisão
`0d3c3eaf220173aa4246916e3d7a226079e87a65`, associou **7.025 valores**
por fabricante e part number exatos. Casos sem correspondência única foram
descartados. Dados existentes e fatos verificados têm precedência.
O OpenDB usa licença CC BY-NC-SA; verifique a compatibilidade antes de uso
comercial.

Para reproduzir a importação após obter essa revisão da fonte:

```bash
poetry run python -m scan_hardware.reported_spec_import \
  --source-root data/raw/buildcores-open-db --publish-package
```

O comando escreve um relatório versionado em `data/processed/specs/buildcores/`.
`src/scan_hardware/curation/reported_specs.json` é o manifesto empacotado.
Cada valor mantém o ID da fonte em `GET /specs/{id}`. O serviço nunca usa um
campo de outra peça para completar lacunas.

## Auditoria em 13/10/2026

| Categoria/campo | Itens com algum valor | Total | Observação |
| --- | ---: | ---: | --- |
| CPU: socket | 325 | 899 | |
| CPU: núcleos | 899 | 899 | 48 conflitos entre fontes |
| CPU: threads | 324 | 899 | |
| CPU: clock base | 899 | 899 | |
| CPU: clock turbo | 458 | 899 | |
| CPU: cache L2/L3 | 138 | 899 | cada campo |
| GPU: VRAM | 7.291 | 7.549 | 103 conflitos |
| GPU: clock base | 6.667 | 7.549 | 109 conflitos |
| GPU: clock turbo | 4.527 | 7.549 | 79 conflitos |
| GPU: tipo de VRAM | 1.660 | 7.549 | |
| GPU: potência | 2.515 | 7.549 | |
| Placa-mãe: socket | 4.426 | 4.426 | 161 conflitos |
| Placa-mãe: formato | 4.426 | 4.426 | 1.232 conflitos |
| Placa-mãe: RAM máxima | 4.307 | 4.426 | 1 conflito |
| Placa-mãe: slots de RAM | 4.306 | 4.426 | 1 conflito |
| Placa-mãe: tipo de RAM | 1.469 | 4.426 | |
| Placa-mãe: frequência RAM sem OC | 2 | 4.426 | |

“Algum valor” inclui conflitos, que aparecem como `null` na API até revisão.
A meta de 99% de dados principais confirmados **ainda não foi atingida**.
O OpenDB não fornece frequência máxima de RAM da placa-mãe e indicador de
overclock de CPU com consistência suficiente para preenchimento em massa.
Esses campos precisam de fichas técnicas por modelo ou outra fonte estruturada
com unidades e identidade verificadas. Não infira uma frequência da geração DDR.

Execute uma auditoria atualizada após cada importação:

```bash
poetry run python -m scan_hardware.catalog_audit
```

## Auditoria de valores utilizáveis em 14/10/2026

O relatório agora inclui `field_summary` por categoria e campo: `usable` conta
valores que a API consegue devolver; `missing` conta ausência; `conflict` conta
fontes divergentes que fazem a API devolver `null`. A chave antiga `coverage`
continua disponível e conta campos presentes, inclusive conflitos.

| Campo principal | Utilizáveis | Ausentes | Conflitos |
| --- | ---: | ---: | ---: |
| CPU: socket | 325/899 | 574 | 0 |
| CPU: threads | 324/899 | 575 | 0 |
| CPU: TDP | 673/899 | 0 | 226 |
| CPU: clock turbo | 458/899 | 441 | 0 |
| GPU: VRAM | 7.188/7.549 | 258 | 103 |
| GPU: clock turbo | 4.448/7.549 | 3.022 | 79 |
| GPU: potência | 2.515/7.549 | 5.034 | 0 |
| Placa-mãe: socket | 4.265/4.426 | 0 | 161 |
| Placa-mãe: formato | 4.425/4.426 | 0 | 1 |
| Placa-mãe: tipo de RAM | 1.469/4.426 | 2.957 | 0 |
| Placa-mãe: RAM máxima | 4.306/4.426 | 119 | 1 |

O campo `size` da segunda fonte classificava como “ATX” placas cujo formato
específico era Micro ATX. Ele deixou de ser interpretado como `form_factor`.
Agora o formato vem da coluna específica ou do nome descritivo quando este
declara explicitamente “ATX”, “Micro ATX” ou “Mini ITX”. Essa correção reduziu
os conflitos de formato de 1.232 para 1, sem inferir pelo código do modelo.
Exemplos conferidos nas fichas da [ASUS PRIME B450M-A](https://www.asus.com/uk/motherboards-components/motherboards/all-series/prime-b450m-a/techspec/),
[MSI MAG B760M MORTAR MAX WIFI DDR4](https://www.msi.com/Motherboard/MAG-B760M-MORTAR-MAX-WIFI-DDR4/Specification)
e [ASRock Fatal1ty Z370 Gaming-ITX/ac](https://www.asrock.com/mb/intel/Fatal1ty%20Z370%20Gaming-ITXac/index.asp).
