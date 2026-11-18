# CLEANUP_MANIFEST

Дата: 2026-11-19. Статус: **READY WITH LIMITATIONS**. Область: только 74-min / Viagra и 59-min / Cialis.

## Состав

Сохраняются runtime, canonical catalogue, все 391 паспорта и используемые manifests/MD, measured specs, обязательные geometry/image fixtures, licences и текущие portfolio docs. Сокращение до двух records разрушило бы общие routing/contract tests, поэтому второй урезанный SSOT не создавался.

389 `01_input_raster/gemini_renders_final` сохраняются неизменными по повторному решению владельца. Это исторический protected dataset, не ещё389 принятых portfolio examples. Все остальные do-not-touch файлы и запечатанные эталоны сохранены.

Из tracking нового candidate исключены raw Gemini renders, 07_input acquisition copies, historical CV/scene/contact-shadow outputs, tooling before snapshots и лишние operator/development notes после dependency analysis. Обязательные 7PNG+7scene blank fixtures и marks index сохранены. Малый transitive Markdown documentation closure оставлен с явным historical label, чтобы архитектурные ссылки не были сломаны.

| Классификация исходного tracked development дерева | Файлы |
|---|---:|
| KEEP_CONTRACT | 394 |
| KEEP_DOCUMENTATION | 859 |
| KEEP_RUNTIME | 65 |
| KEEP_SOURCE_DATA | 691 |
| KEEP_TEST | 143 |
| REMOVE_FROM_TRACKING | 1488 |

Все named files и основания: [cleanup-files.json](docs/portfolio/cleanup-files.json). Точный final public набор содержит 2207 файлов на момент отчёта; development-tree и public-parent counts различаются из-за разных исходных веток. Удалено из tracking публичного parent 816 путей. Эти числа не считаются уменьшением исторической Git-базы.

## Безопасность

Оригинальные файлы не удалялись и не переключались. Операции `git rm --cached` применялись только в независимых копиях по поимённым manifest; рабочие файлы и private recovery сохранены. `git add -A`, `git add .`, force push, rebase и переписывание публичной истории не использовались. Старые ветки не удалялись.

G0 повторно проверил SHA-256 90 487 файлов и восстановление трёх bundles, refs и fsck; accepted PNG совпали. Исходная raw Git metadata с четырьмя zero app refs сохранена как forensic data; valid history восстановлена из bundle в независимый Git. `.gitattributes` сохраняет точные bytes SHA-pinned asset sources при checkout.

В публичную копию не включены исходные Reference Templates photographs, приватные recovery inventories/logs или employer photo inputs. Physical путь не требует этих фотографий. Новые previews lossless-derived от подтверждённых PNG; restricted asset rights не перелицензированы свободной лицензией.
