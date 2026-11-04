# Mudanças recentes do Hardware Scanner

Atualizado em 04/11/2026. Este documento resume as entregas dos PRs
[#21](https://github.com/Mathwesm/scan_hardware/pull/21) a
[#26](https://github.com/Mathwesm/scan_hardware/pull/26), já incorporados à `main`.
O [guia de integração](integracao.md) contém o contrato completo da API.

## O que mudou

| Área | Mudança | Uso no aplicativo |
| --- | --- | --- |
| Catálogo por categoria | `GET /catalog/{category}` lista peças com paginação. As quatro categorias das abas são `motherboard`, `ram`, `cpu` e `gpu`. | Carregar a aba escolhida sem baixar o catálogo inteiro. |
| Dados para as abas | Cada item da lista tem os campos planos já usados nos candidatos de `/scan`, além do `id`; valores desconhecidos são omitidos. | Reutilizar o modelo de peça no cliente e abrir `GET /specs/{id}` para detalhes. |
| Relação por socket | `GET /specs/{id}/socket-related` lista CPUs de uma placa-mãe ou placas-mãe de uma CPU com o mesmo socket, usando `limit` e `offset`. | Apresentar peças relacionadas na tela de detalhes. |
| Filtro de compatibilidade | A busca por socket passou a excluir divergências conhecidas de fabricante, chipset e gerações Intel LGA1151. | Evitar, por exemplo, indicar Ryzen numa placa Intel. |
| Especificações | Houve complementação de modelos exatos a partir de fontes identificadas; valores ausentes ou conflitantes não são inventados. | Exibir somente campos presentes na resposta. |
| Imagens | Foram acrescentadas referências verificadas de CPUs e um fluxo de descoberta e revisão de imagens para placas-mãe sem foto. | Mostrar `image_url` quando vier; manter uma imagem substituta quando faltar. |
| Demonstração | `/demo` passou a apresentar detalhes e peças relacionadas em uma interface, em vez de exigir que o usuário leia o JSON bruto. | Testar visualmente o catálogo antes de integrar o app. |

As rotas existentes `POST /scan`, `POST /lookup` e `GET /specs/{id}` continuam
disponíveis. A inclusão das abas não mudou o formato das respostas de scan.

## Como usar as quatro abas

Use a mesma base de API para cada categoria:

```text
GET /catalog/motherboard?limit=20&offset=0
GET /catalog/ram?limit=20&offset=0
GET /catalog/cpu?limit=20&offset=0
GET /catalog/gpu?limit=20&offset=0
```

O retorno tem esta estrutura:

```json
{
  "category": "cpu",
  "total": 899,
  "limit": 1,
  "offset": 0,
  "items": [
    {
      "category": "cpu",
      "brand": "AMD",
      "model": "AMD 2650",
      "id": "cpu-6133918f943e142a8ee08cf8",
      "price_status": "unavailable",
      "base_clock_ghz": 1.45,
      "cores": 2,
      "tdp_w": 25,
      "integrated_graphics": "Radeon HD 8240",
      "smt": false
    }
  ]
}
```

O exemplo mostra somente o primeiro item de uma consulta local com `limit=1` em
04/11/2026; `total` e os produtos variam conforme a versão importada do catálogo.
Na aplicação, incremente `offset` pela quantidade recebida e pare ao atingir
`total`. `limit` aceita de 1 a 100. Use `id` em `GET /specs/{id}`; para a relação
por socket, consulte `GET /specs/{id}/socket-related?limit=20&offset=0`.

O aplicativo deve mostrar `model` diretamente no título: esse valor já pode
conter o fabricante. Concatenar `brand` com `model` produz títulos duplicados,
como `Gigabyte Gigabyte GA-78LMT-USB3`.

## Validação realizada

- O PR #26 passou no CI do GitHub, incluindo o controle de qualidade no Linux e
  a integração com PostgreSQL.
- A suíte local do PR #26 terminou com **162 testes aprovados e 1 ignorado**.
  Ruff, mypy e o verificador de segredos também passaram.
- No catálogo local testado, as quatro rotas responderam com HTTP 200 e
  paginação: 4.426 placas-mãe, 1.707 memórias RAM, 899 CPUs e 7.549 GPUs.
  Essas contagens não são uma garantia de cobertura de todos os modelos do mercado.

## Limites conhecidos

- **Mesmo socket não garante compatibilidade final.** BIOS, revisão da placa e
  lista oficial de CPUs do fabricante ainda precisam ser conferidas antes de
  afirmar que uma CPU funciona naquela placa.
- Parte do catálogo ainda não tem foto ou todas as especificações. Campo ausente
  indica dado indisponível ou conflitante; não equivale a zero.
- As fotos de teste documentadas em [validação de campo](field_validation.md)
  cobrem poucos produtos e variantes de imagens. Elas não demonstram taxa geral
  de acerto de OCR de 95% em fotos de celulares diferentes.
- A busca de imagens exige revisão da correspondência entre marca, modelo e foto
  antes de publicar uma associação. O fluxo está em [imagens](image_enrichment.md).

## Referências rápidas

- [README](../README.md): instalação, importação da base e inicialização.
- [Integração](integracao.md): autenticação, JSON, rotas e tratamento de erros.
- [Especificações complementares](especificacoes_complementares.md): origem e
  atualização dos dados adicionais.
- [Validação de campo](field_validation.md): ensaios com fotos e limites da amostra.
