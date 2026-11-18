# RENDERER_SCOPE_DECISION

Дата: 2026-11-19. Статус: **READY WITH LIMITATIONS**. Область: только 74-min / Viagra и 59-min / Cialis.

`reference_projection` — исторический фото-texture/camera/exposure эксперимент. Ни текущие catalogue specs, ни сохранённая accepted physical цепочка двух hero не требуют его активации. Physical builder отдельно запрещает фотографические поля.

По новому ТЗ эксперимент исключён из публичного candidate: не импортированы `src/reference_projection.py`, `scripts/render_reference_projection.py`, `tests/test_reference_projection_contract.py`; удалены его driver helpers/dispatch/dump/camera/exposure branches, provider hooks и schema1.12. Удаление не выполнялось в исходных worktrees или recovery. Уникальный исходник и связанные старые tests сохранены приватно.

Сохранены physical1.13, legacy1.10/1.11, compound mark geometry и единый owner routing/manifest. Physical main-dispatch AST совпал с восстановленным до выделения эксперимента; текущие render outputs совпали с прежними recovery outputs. Принятые исторические PNG остаются отдельными original artifacts.

Новый regression test сначала показал, что schema принимала1.12, затем подтвердил отказ от retired version. Existing schema/manifest/driver checks сохранены. Изменённые test fixtures генерируют temporary artwork самостоятельно и не требуют private generated caches.

Для отсутствующей optional photography проверка явно NOT VERIFIED/skip. Если данные присутствуют частично или повреждены, сохраняется FAIL/error; producer SystemExit преобразован в AssertionError только в test setup, чтобы он не завершал весь suite. Synthetic/geometry assertions и пороги не ослаблены.

Исключения INV-006/INV-008 действуют только для physical mode по явному решению владельца. Legacy текст остаётся геометрией; bpy импортируется только driver. Фатальные driver errors завершаются через SystemExit. Новый renderer или новые SKU-шаблоны в этом release не разрабатывались.
