# Field validation with public hardware photos

Validation date: 2026-10-08 UTC. The images and raw responses are retained locally under
`data/validation/20261008T012749796270Z/` and are excluded from Git.

## Photo results

All photos were downloaded from their Wikimedia Commons file pages for local testing.
The `/scan` endpoint received the actual JPEG bytes. A crop is a framing experiment,
not a different component.

| Component | Source photo | Input | Result |
| --- | --- | --- | --- |
| Intel Core 2 Duo E8400 | [Eric Gaba, CC BY-SA 4.0](https://commons.wikimedia.org/wiki/File:Intel_CPU_Core_2_Duo_E8400_Wolfdale_top.jpg) | Full photo | Exact match after adding the unique `E8400` alias; 3.51 s for the complete HTTP scan. |
| ASRock A320M-DVS R4.0 | [Jacek Halicki, CC BY-SA 4.0](https://commons.wikimedia.org/wiki/File:2023_P%C5%82yta_g%C5%82%C3%B3wna_ASRock_A320M-DVS.jpg) | Full photo | OCR reads `A320M-DVS`; the revision is not legible, so the expected item ranks first as a suggestion; 4.94 s. |
| MSI GTX 1050 Ti 4GT OC | [ITEagle Europe / Sebastiaan Broekhoven, CC BY-SA 4.0](https://commons.wikimedia.org/wiki/File:MSI_GeForce_GTX_1050_Ti_4GT_OC_-_rear_view.jpg) | Full photo | Exact match after joining neighboring OCR lines in reverse order; 3.14 s. |
| MSI GTX 1050 Ti 4GT OC | Same source | Rotated, tight label crop | Exact match; OCR reads `GeForce GTX 1050 Ti 4GT OC`; 1.99 s. |
| MSI GTX 1050 Ti 4GT LP | [Robbie Klinkenberg, CC BY-SA 4.0](https://commons.wikimedia.org/wiki/File:MSI_GTX_1050_TI_4GT_LP.jpg) | Front photo | No match; the model is not printed on the visible side; 1.84 s. |

Earlier E8400 photos from [Michael Wolf](https://commons.wikimedia.org/wiki/File:Intel_Core2Duo_E8400_IMG_8141.jpg)
and a [CC0 photo](https://commons.wikimedia.org/wiki/File:Processor_INTEL_CORE_2_DUO.jpg)
were also tested. OCR read `E8408` and `E8409`, respectively. An incorrect digit must
not produce an exact identification.

## CPU fields already retained

The endpoint `GET /items/{id}/sources` returns every original source row and column.
It was checked against the imported Intel Core i3-7350K and E8400 records.

| Dataset | CPU rows | Available fields | Missing fields of interest |
| --- | ---: | --- | --- |
| `pc-parts-by-type` | 458 | `brand`, `socket`, `speed`, `coreCount`, `threadCount`, `power`, `name`, `image`, `url` | Cache, process node, supported memory, PCIe version. |
| `warcoder/pc-parts` | 1,341 | `core_count`, `core_clock`, `boost_clock`, `tdp`, `graphics`, `smt`, `price`, `name` | Socket, explicit thread count, cache, process node, supported memory, PCIe version. |

All 458 first-dataset rows contain socket, base speed, core count, thread count,
and power. All 1,341 second-dataset rows contain core count, base clock, TDP, and
SMT. Boost clock is non-null on 659 rows; graphics on 575. For example, the
E8400 source row contains 2 cores, 3 GHz and 65 W, but no socket. An [Intel
support table](https://www.intel.com/content/www/us/en/support/articles/000007669/server-products.html)
lists its socket as LGA775; that value is not imported into the catalog.

At the distinct-item level, the current catalog has 899 CPUs: 318 have a source
socket and explicit thread count; all 899 have normalized core count, base clock,
and TDP; 456 have a boost clock.

There is a real source conflict for the i3-7350K: `pc-parts-by-type` says
`power=50`, while `warcoder/pc-parts` says `tdp=60`. Intel's
[official comparison](https://www.intel.com/content/www/us/en/products/compare.html?productIds=97527)
lists 60 W. A unified specification response must keep provenance, detect such
conflicts, and incorporate verified manufacturer values before resolving them.

The API now adds a `specifications` map to each returned item. Every property
contains a normalized value, unit, status (`reported` or `conflict`), and distinct
source evidence. A conflict has `value: null` until authoritative evidence is
imported. The complete source rows remain available at `/items/{id}/sources`.
The other categories are also mapped: GPUs include chipset, VRAM, clocks, power,
length, resolution class and color; motherboards include socket, form factor,
memory capacity, slot count and color when the source has them.

The photographed MSI GPU exposes a `vram_gb` conflict (2 versus 4 GB). The
[manufacturer specification](https://www.msi.com/Graphics-Card/GeForce-GTX-1050-Ti-4GT-OC/Specification)
lists 4 GB. The ASRock board exposes a form-factor conflict (`ATX` versus
`Micro ATX`); the [manufacturer specification](https://asrock.com/mb/amd/A320M-DVS%20R4.0/)
lists Micro ATX. These manufacturer facts were checked for validation and are
not yet loaded as a catalog-wide enrichment source.

## Specification coverage and conflicts

The audit counted distinct catalog items with a source value for each field. A
conflicting value counts as covered, but its normalized `value` remains `null`.
These are source-data counts, not independently verified hardware facts.

| Category | Field | Covered items | Conflicts |
| --- | --- | ---: | ---: |
| CPU (899) | Cores | 899 | 48 |
| CPU (899) | Base clock | 899 | 0 |
| CPU (899) | TDP | 899 | 228 |
| CPU (899) | Socket | 318 | 0 |
| CPU (899) | Threads | 318 | 0 |
| CPU (899) | Boost clock | 456 | 0 |
| GPU (7,549) | VRAM | 7,291 | 104 |
| GPU (7,549) | Chipset | 5,248 | 0 |
| GPU (7,549) | Board power | 2,514 | 0 |
| Motherboard (4,424) | Socket | 4,424 | 161 |
| Motherboard (4,424) | Form factor | 4,424 | 1,233 |
| Motherboard (4,424) | Max memory | 4,227 | 1 |
| Motherboard (4,424) | Memory slots | 4,227 | 1 |

The high motherboard form-factor conflict count and CPU TDP conflict count make
source verification a prerequisite for displaying those values as definitive.
The API exposes the disagreements so a client can ask for confirmation or omit
the disputed value. The full audit is retained locally in
`data/validation/20261008T012749796270Z/specification_audit.json`.

## Image-link audit

The imported catalog initially contained 4,684 item image URLs. A sampled HEAD
request succeeded for 12/12 Amazon-hosted URLs. Three Wikimedia entries all
pointed to the same nonfunctional `No_image_available` placeholder. The importer
now removes that placeholder; the republished catalog contains 4,655 items with
image URLs. The 3,327 PCPartPicker CDN URLs were not probed because its
[robots.txt](https://pcpartpicker.com/robots.txt) limits automated access.

The image URLs remain third-party references, not licensed local product images.
Wikimedia images are governed by the license on each file page and need attribution
where applicable. No reference photo is bundled in the repository.

## Remaining limits

- A phone should frame the printed model or sticker clearly. A side of the
  component with no visible model code cannot be identified by this OCR service.
- A model revision that is not legible should remain a suggestion. The app should
  ask the user to confirm rather than assert a specific revision.
- The saved motherboard OCR text now searches the full catalog in 1.24 s
  locally; the complete OCR and HTTP scan took 4.94 s. Timing varies with the
  host and photo, and mobile network latency was not measured.
- The mobile client and external backend were not available, so only the
  standalone HTTP service was exercised.
