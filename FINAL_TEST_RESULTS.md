# FINAL_TEST_RESULTS

Дата: 2026-11-19. Статус: **READY WITH LIMITATIONS**. Область: только 74-min / Viagra и 59-min / Cialis.

## Тесты

Локальный чистый source-copy run: `python -B -m unittest discover -s tests -v`, Ran624 in750.709s, `OK (skipped=14)`. Журнал содержит611 успешных test statuses и13 method skips; ещё один class-level fixture skip исключает4 метода и отдельно не входит в testsRun. Не вычислять число pass простым624−14.

Structured published clean-checkout run: collected=628, testsRun=624, passed=611, failed=0, errors=0, skip records=14, exit=0, seconds=707.234. Подробный счёт method/class fixture skips и GitHub receipt: [published-verification.json](docs/portfolio/published-verification.json).

Первая clean попытка выявила missing-photography FAIL и class-fixture SystemExit, оборвавший suite после601 ok. Fixture handling исправлен; quality assertions не ослаблены. Первый успешный unittest log сохранён целиком; private run wrapper после завершения тестов ошибся при postprocessing kind-name и не сохранил return-code JSON. Ошибка обвязки исправлена, журнал unittest не переписан; authoritative published structured run учитывает successes/skips напрямую.

## Остальные проверки

- Python compilation: все выбранные source files проверяются компилятором; publication source compilation: 111 Python files,0 errors (включая root entry points).
- JSON Schema корректна;391 legacy manifests построены каноническим provider и валидированы.
- Required physical imports и все11 declared dependency constraints удовлетворены установленными версиями.
- Driver smoke / fatal-exit / engine checks выполнены existing tests; два full physical hero renders завершились exit0.
- Geometry/layout/material gates обоих SKU PASS; exact original byte/pixel equality FAIL, visual regression не выявлена.
- Whole-frame hero OCR частичный; не объявляется100% автоматической приёмкой.
- Optional historical measurement SciPy объявлена отдельно; не требуется core physical path.
- Markdown relative links и secret/PII review выполняются по точному публичному набору, а не по оставшимся private files на диске.

Пропуски NOT VERIFIED: optional reference-photo dataset, PHARMAGEN_SLOW_TESTS render/OCR checks, current-era silhouette measurements и producer photo fixture. Они не засчитаны как PASS. Raw history R-004 с неизвестным старым упавшим тестом не закрыт двумя зелёными современными проверками.

Проверки выполняются в одноразовых копиях/клонах; private generated caches не переносились. Никакие credentials или платные AI API не использовались для render/test verification.
