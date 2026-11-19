# FINAL_SCENE_AND_MASKS_AUDIT

Дата: 2026-11-19. Статус: **VALIDATED — PUBLICATION CHECKS PENDING**.

## Резюме

Сохранён полноценный редактируемый 3D-проект двух SKU: [Viagra](examples/74_viagra/README.md), [Cialis](examples/59_cialis/README.md). Исходная папка `renders` не удалялась, не очищалась и не перезаписывалась. Все56 исходных элементов верхнего уровня и рекурсивное содержимое учтены:77 файлов,2 каталога,1 202 245 421 bytes. Отдельный backup проверен SHA-256; два внешних шрифта невыбранной legacy-сцены дополнительно сохранены. [Полный inventory](RENDER_ASSET_INVENTORY.md), [machine manifest](RENDER_ASSET_INVENTORY.json), [validation receipt](docs/portfolio/scene-validation.json).

## Четыре независимых результата

| Проверка | Результат |
|---|---|
| Historical accepted image preservation | PASS: исходные PNG и два опубликованных WebP сохранены по SHA; lossless связь previews с PNG не изменена |
| Editable scene integrity | PASS: финальные очищенные binaries открыты и отрендерены в чистом клоне, mesh/UV/material/camera/light/render state сохранён |
| Fresh procedural rendering | PASS: один новый hero цикл на SKU через существующий CLI; bytes совпали с fresh baseline предыдущего выпуска |
| Visual regression | PASS с прежними ограничениями: saved-scene replay дал точные accepted pixels; procedural отличается от исторических PNG, как раньше |

| SKU | Все объекты | Packed / external textures | Saved replay: отличающихся pixels от accepted | Procedural: pixels от accepted |
|---|---|---|---:|---|
| 74-min | 87 (80 mesh) | 5 / 0 | 0 | 652 / max1 |
| 59-min | 52 (45 mesh) | 4 / 1 | 0 | 501 / max1 |

Каждая сцена содержит4 камеры и3 источника света. Активна `camera_hero`, CYCLES CPU,32 samples,2048². Наличие редактируемой геометрии не заменено image planes. В tested Blender5.1.2/ec6e62d40fa9 оба saved replay совпали с accepted по всем RGBA pixels. После существующей color-only PNG metadata policy совпали и SHA файлов. Raw Blender PNG содержат volatile timing/text chunks и поэтому их bytes сравниваются отдельно. Это наблюдение данной среды, не cross-version/cross-machine determinism и не известный creation Git revision.

## Выбор и перенос сцен

Выбраны `74-min-deterministic-repeat.stage.blend` и `59-min-proportion-final.stage.blend`: SHA самих оригинальных файлов совпали с historical JSON, который связывает их с accepted PNG hashes. Дополнительные исторические варианты также сохранены приватно. Ни один файл не переименован в approved.blend.

Публичные `.blend` — derived saves с относительными resource/output paths. Viagra содержит5 packed maps. У Cialis4 packed maps, а normal map вынесена в `textures/normal.png` с теми же bytes/SHA и ссылкой `//../textures/normal.png`: исходный113,9MB blend превышает GitHub100MiB file limit. Ни геометрия, ни UV, ни shader values, ни камеры, ни свет, ни render settings ради переноса не менялись. Все public files меньше100MiB; Git LFS не требуется.

Сравниваются mesh buffers/UV/material node inputs+links/image-content hashes/camera/light/render records. Из semantic fingerprint исключены только output filenames/paths, ephemeral session_uid, неиспользуемый default Material и VIEWER framebuffer caches. Первое сравнение audit helper обнаружило именно эти несодержательные поля; лог сохранён, visual properties не подгонялись. Дополнительно финальные binaries проверены реальным render.

## Зависимости и privacy

В выбранных сценах нет fonts, linked libraries, scripts/drivers, external caches или sequence inputs. Все необходимые FILE images загружены из packed data либо из relative normal map внутри чистого клона. Original root не требуется. Имена generated output направлены в `reports`, не в исторические masks.

Независимый binary review выявил служебный FileBrowser directory и старые ImagePackedFile paths. Они очищены только в derived copies через Blender API; исходники и первые копии сохранены приватно. После сохранения/reopen fingerprints совпали; полный zstd-decompressed scan не нашёл private profile/OneDrive/old-source-root tokens и credential patterns. Предварительный private commit с этими строками не является предком публичной ветки. Предупреждения RNA о colorspace относятся к unused VIEWER buffers; необходимые FILE textures имеют заданные sRGB/Non-Color spaces и загружены.

## Маски

Все19 исходных masks сохранены побайтово в каталогах примеров. Это2048² BW Object Index/compositing outputs, не texture inputs материала. Procedural artwork layout_masks — отдельная сущность. Для двух новых hero mask outputs наблюдаются raw различия до1/255 при совпадающем бинарном support≥128. Причина малых различий не установлена; точная регенерация масок не заявляется, пороги не снижались. Поэтому ни одна историческая маска не исключена. Старые JSON pin PNG SHA, но не mask SHA: mask associations помечены PATH_ONLY_UNVERIFIED_MASK_BYTES. PNG associations требуют полного relative path и совпадающего SHA.

## Публикация и граница

Candidate проверен локально. Публикация сцен и post-publication clone ещё не подтверждены; готовность опубликованного addendum пока не объявляется.

Runtime, schemas, contracts и tests относительно release13eb0c1 не менялись. Предыдущий full unittest result611 PASS/0FAIL/0ERROR/14skip records остаётся историческим результатом проверенного кода; новый full suite ради binary/docs-only changes не запускался. Текущий addendum проверен scene opens, двумя final saved renders и двумя procedural renders, hashes, dependency closure, Markdown/security и независимым review. Первые2 saved renders до metadata sanitization также сохранены в evidence; final binaries проверены повторно из отдельного чистого clone.

Права основаны на подтверждении владельца, без independently inspected instruments или blanket commercial/trademark sublicense. Сохраняются неизвестный creation Git revision, optional/slow checks/R-004, оценочные материалы/размеры и прежние OCR/визуальные ограничения. Остальные389 SKU не дорабатывались. После публикации исходный renders остаётся неизменным до отдельного подтверждения владельца.
