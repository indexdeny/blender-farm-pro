# ACCEPTED_RENDER_PROVENANCE

Дата: 2026-11-19. Статус: **READY WITH LIMITATIONS**. Область: только 74-min / Viagra и 59-min / Cialis.

## Принятые оригиналы

Владелец подтвердил принятие на работе ровно `74-min-hero.png` и `59-min-hero.png`. Это owner-reported workplace acceptance, а не сертификация производителя. Оба оригинала — 2048×2048, сохранены неизменными в приватном recovery. Публичные lossless WebP используют те же декодированные RGBA-пиксели; файлы и SHA приведены в [preview-provenance.json](docs/portfolio/preview-provenance.json).

| SKU | SHA-256 оригинального PNG | Различающихся пикселей fresh | Max delta канала | PSNR RGB, дБ |
|---|---|---:|---:|---:|
| 74-min | `27a4dfbc3dabc3d474c2c35090f6d4147aa4d3d48a48fbe18189055f8e3ab97c` | 652 | 1 | 90.99 |
| 59-min | `0f9946529464cb5778d9e2d5d006d6711aaef075c8697c36dc55c2a8d6f7a9b7` | 501 | 1 | 92.13 |

## Реализация и зависимости

Основной source candidate владельца — `corner-trial-74-viagra` / `033632e`. Реальный physical код найден в descendant `codex/reference-design-producer` / `bd849c1` и его незакоммиченном worktree. Восстановленный checkpoint — `a68cae27175870dc8096a693df95b922843de901`. Точный creation Git revision двух PNG — **UNKNOWN**; известный base SHA его не заменяет.

Выбранный public code commit: `f20565b3c67412197f37b46226edc9fc165b4887`. История публикации начинается от проверенного публичного master `c066fbc71ff1f4c5ca2f06b6faaf2a376f7be486`; выбранный end-state перенесён новыми commits. Приватные несвязанные development commits не публикуются и сохраняются в recovery bundles.

Driver: `05_assets/blender/render_driver.py`; канонический manifest owner: `src/render_manifest.py`, schema: `schemas/render_manifest.schema.json`, physical contract 1.13. Config: `config.yaml`. Specs: `Reference Templates/74_Viagra/design_spec.json` и `59_Cialis/design_spec.json`, секции `baseline_rebuild`. Все 11 уникальных SVG/TTF input-хешей проверены; fonts/font licences сохранены. На приёме использовались uncommitted runtime-модули `src/carton_*`, schema и изменения driver/provider; один HEAD primary candidate их не содержит.

Архивная closure-цепочка содержит 84 проверенные path/SHA-ссылки и 218 source files с совпавшими архивными SHA. Текущий восстановленный source совпадал с accepted archive по 215/218 файлам; три отличия — baseline schema, carton_spec и carton_validate. Provenance выше не является заявлением exact reproduction.

## Контролируемое воспроизведение

Выполнен один fresh hero cycle для каждого SKU, без reuse-artwork. Blender 5.1.2, build ec6e62d40fa9, Python3.10.11, Cycles CPU; зависимости и source hashes: [environment](docs/portfolio/reproduction-environment.json). Оба запуска exit0. Новые PNG не совпали с accepted originals по bytes или pixels, но совпали с предыдущими recovery rerenders.

С исторической сценой совпали mesh/UV/bounds/material records для 78 объектов Viagra и 43 Cialis, четыре camera matrices/intrinsics на каждый SKU, render contract и shader inputs. Layout/geometry/material gates из существующих specs — PASS, без изменения порогов. Base-color карты имеют небольшие численные различия до2/255, roughness до1/255; metallic/height/normal SHA совпали. Причина изменения rasterization/numerics не установлена.

Полные accepted/fresh пары просмотрены: заметной регрессии геометрии, ориентации, кадрирования, света, цвета, композиции и основных надписей не выявлено. Сохранены исторические ограничения, включая частичное пересечение Braille/wordmark у Cialis и оценочные покрытия/размеры. Это малое численное отклонение при сохранённой композиции, **не exact equality** и не доказательство производственной подлинности.

Whole-frame OCR существующим backend распознал дозировку100mg/количество30 для Viagra и количество30 для Cialis, но не все brand/dose поля. Human readability проверена отдельно. Полная автоматическая OCR-приёмка physical hero не заявляется. Численные метрики: [render-verification.json](docs/portfolio/render-verification.json).

## Права

Владелец 2026-11-19 подтвердил наличие права показывать оба PNG и основания распространять используемые брендовые SVG для этого портфолио. Разрешительные документы независимо не изучались. Источники, ограниченные лицензии и отсутствие blanket commercial/trademark sublicense: [ASSET_RIGHTS.md](docs/portfolio/ASSET_RIGHTS.md).

## Addendum: editable scenes and masks (2026-11-19)

Две редактируемые сцены и необходимые ресурсы сохранены в examples; все19 исходных masks и два historical JSON evidence перенесены без изменения bytes. Saved-scene replay в проверенной среде восстановил exact accepted pixels/normalized PNG hashes; procedural replay отдельно сохранил baseline прошлого выпуска. Это разные результаты. Текущий статус и ограничения: [FINAL_SCENE_AND_MASKS_AUDIT.md](FINAL_SCENE_AND_MASKS_AUDIT.md), [inventory](RENDER_ASSET_INVENTORY.md).
