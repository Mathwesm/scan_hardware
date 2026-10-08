# Hardware catalog source assessment

Assessment date: 2026-10-07. Scope: motherboards, graphics cards, and processors, including older products and their printed model or part identifiers.

## Recommendation

Start with a **Kaggle dataset audit**, because the requested source is Kaggle. The strongest directly relevant candidate so far is `rohitmit98/pc-parts-by-type`: it has all three categories, product names with many part codes, and image URLs. A second candidate, `warcoder/pc-parts`, has more records and specifications but no image URLs or declared license. Neither has yet demonstrated the required historical breadth. Keep source, provenance, and image rights attached to each record. Do not treat a generic GPU chipset and a manufacturer's board SKU as the same product.

The current scanner schema (`category`, `brand`, `model`, `identifiers`, `image_url`) is only a lookup catalog. Importing detailed specifications requires a reviewed database migration and a batch ingestion pipeline. Do not load a large feed through the single-item HTTP endpoint.

## Candidate sources

| Source | Useful data | Access and reuse | Assessment |
| --- | --- | --- | --- |
| Kaggle: `rohitmit98/pc-parts-by-type` | 458 CPUs, 2,515 GPUs, 2,422 motherboards; model, category, selected specs, image URL and product URL | Dataset declares CC0; its description says it was assembled from PCPartPicker and Wikipedia | Downloaded all eight CSVs for local evaluation. Image URLs point to third-party hosts; the declared dataset license does not establish image rights. Historical coverage is unverified. One sample motherboard has `Micro ATX` in its name but `ATX` in its size column. |
| Kaggle: `warcoder/pc-parts` | 1,341 CPUs, 5,669 video cards, 4,249 motherboards, with selected specs | Dataset license is listed as unknown | Downloaded all 25 JSON files for local evaluation. No images or manufacturer part numbers in these three files. GPU names can repeat across different chipsets, so the importer uses name plus chipset. Historical coverage is unverified. |
| Kaggle: `riyagarg0314/gpu-specs-database-nvidia-and-amd-1995-2026` | 1,943 Nvidia and AMD GPU chip models with launch dates and technical fields | CC BY-SA 4.0; uploader says it was compiled from Wikipedia tables | Downloaded for evaluation. Useful historical chip reference, but it identifies GPU models rather than partner video-card SKUs and has no product photos. It is not loaded into the board-level scanner catalog. |
| Open Icecat | Brand, product code/MPN, mapped codes, GTIN, category, specifications, release dates, image references | Free registration; documented XML/JSON/CSV channels; Open Content License and Fair Use Policy | Alternative source if Kaggle coverage proves insufficient. Some brand assets can have additional restrictions. |
| Wikidata | CC0 structured facts and identifiers | Public data access and dumps; media files have separate licenses | Useful for cross-checking and gaps, but completeness at manufacturer SKU and image level is unverified. |
| TechPowerUp GPU/CPU databases | Broad historical reference data | Its robots.txt explicitly prohibits automated data mining and scraping without written permission | Reference for manual comparison only. Do not import or crawl without permission. It also does not solve motherboard SKU coverage. |
| Unofficial PCPartPicker dataset on Hugging Face | CPUs, motherboards, GPUs, specs, image URLs | Dataset uploader labels it MIT, but says the data came from PCPartPicker and images remain hosted elsewhere | Do not make this the primary feed until underlying data and image reuse rights are verified. |

## Kaggle download and evaluation

The complete public dataset archives are stored locally at `data/raw/kaggle/pc-parts-by-type.zip` and `data/raw/kaggle/warcoder-pc-parts.zip`. They remain outside Git through `data/` in `.gitignore`. The Kaggle public API permits anonymous downloads of public datasets. The archives contain every original file and column, without selecting only a preview.

The first archive has `CPU.csv` (10 columns), `GPU.csv` (8 columns), and `Motherboard.csv` (7 columns). Every row has a nonempty image field, but some values are placeholders such as `https://static/forever/img/no-image.png`. The importer excludes those placeholders. The remaining URLs have not been tested for accessibility or reuse rights. The second archive has `dataset/cpu.json` (8 fields), `dataset/video-card.json` (9 fields), and `dataset/motherboard.json` (8 fields). Neither archive contains an explicit release-year field in these three categories. Before production use, assess decade coverage with manufacturer release references or other reliable dates, quantify duplicates, and validate image availability and rights.

The two user-downloaded archives in `Downloads` have SHA-256 hashes identical to the two local archives. A first duplicate audit found 458/458 unique CPU names, 2,515/2,515 GPU names, and 2,422/2,422 motherboard names in `rohitmit98`; 897/1,341 unique CPU names, 3,331/5,669 unique video-card names, and 4,234/4,249 unique motherboard names in `warcoder`. Parenthesized part-code candidates appear in 458 CPU, 2,498 GPU, and 2,337 motherboard names in `rohitmit98`; they still need validation as manufacturer identifiers. A sample search found older Core 2 Duo products in `warcoder` but none of the queried legacy examples in `rohitmit98`. This is a spot check, not a measured release-decade distribution.

The validated local import has 899 CPU, 7,549 GPU, and 4,424 motherboard products. Of these, 4,684 products have a plausible external image URL. All 16,654 relevant source rows were imported; none were rejected in this run. GPU names shared across different chipsets are separate products, and an image is joined only if the chipset also agrees. These figures describe URL presence, not confirmed image availability or permission to redistribute the photographs. A Kaggle search for model-specific hardware photos did not reveal a second broad product-image catalog; the prominent PC-parts image dataset is for category classification rather than SKU lookup.

## Open Icecat details to validate if needed

The current Icecat manual describes lookup by Icecat ID, GTIN, or brand plus product code. Its index includes category ID, official and mapped product codes, model name, update timestamp, and main image reference. Product XML includes release/end-of-life fields and features. This matches the scanner's identifier-first workflow better than a generic CPU/GPU benchmark list.

Before importing, audit the Open feed by category and publication decade. Report at least:

- Product counts for motherboard, graphics card, and CPU categories.
- Counts by release decade and by manufacturer.
- Share with an MPN, product image, and usable specifications.
- Duplicate or conflicting normalized identifiers, especially board revisions and partner GPU variants.
- A manual sample of older products to estimate OCR-match usefulness.
- Whether attribution, disclaimer, redistribution, and image usage in the intended app comply with the current license.

The official subscription page states that Open Icecat has limited brand/category coverage compared with Full Icecat. Do not extrapolate a total catalog count to these three categories. The current Open Content License requires a free account and excludes machine-learning training use. This project would use the data for lookup, not OCR model training; the intended product display still needs to follow the license's attribution and disclaimer terms.

## Proposed canonical record

`source`, `source_product_id`, `source_url`, `source_updated_at`, `license_id`, `category`, `brand`, `model`, `manufacturer_part_number`, `aliases`, `gtins`, `release_date`, `end_of_life_date`, `specifications`, `image_url`, `image_license`, `quality_status`.

Store source records separately from normalized products. Preserve raw input, reject malformed records with a reason, and publish only after category counts and field-completeness checks pass. Exact OCR matches should require a manufacturer identifier where available; fuzzy matches remain suggestions.

## References

- Open Icecat subscription: https://icecat.com/content-subscription/
- Open Icecat API manual: https://iceclog.com/open-catalog-interface-oci-open-icecat-xml-and-full-icecat-xml-repositories/
- Open Icecat license: https://iceclog.com/open-content-license/
- Open Icecat fair use policy: https://iceclog.com/open-icecat-fair-use-policy/
- Wikidata data licensing: https://www.wikidata.org/wiki/Wikidata:Licensing
- Wikidata data access: https://www.wikidata.org/wiki/Wikidata:Data_access
- TechPowerUp robots policy: https://www.techpowerup.com/robots.txt
- Unofficial PCPartPicker dataset: https://huggingface.co/datasets/Doshiba/pcpartpicker-parts-dataset
- Kaggle PC Parts by Type: https://www.kaggle.com/datasets/rohitmit98/pc-parts-by-type
- Kaggle PC Parts: https://www.kaggle.com/datasets/warcoder/pc-parts
- Kaggle historical GPU specifications: https://www.kaggle.com/datasets/riyagarg0314/gpu-specs-database-nvidia-and-amd-1995-2026
- Kaggle public API: https://www.kaggle.com/docs/api
