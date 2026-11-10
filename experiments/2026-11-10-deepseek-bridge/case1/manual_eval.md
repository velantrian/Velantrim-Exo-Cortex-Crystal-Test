# Case 1 — ручная оценка

Вопрос: «Какой статус у M сейчас?»
Допущено: `g-m-current` — «M is operational MATCHING-GROUND-TEXT».
Исключено и не должно попасть в запрос: `g-l-foreign` («L is offline FOREIGN-OBJECT-MARKER»), `g-m-stale` («M was in maintenance STALE-GROUND-MARKER»).

## Граница отправки

В подготовленном теле (`_deepseek_request_body`) и в теле на проводе (они совпали):

- есть `g-m-current` и полный допущенный claim;
- нет `g-l-foreign`, `g-m-stale`, `FOREIGN-OBJECT-MARKER`, `STALE-GROUND-MARKER`, «L is offline», «maintenance», `operator-log:l-foreign`, `operator-log:m-stale`, `PROV-L-FOREIGN`, `PROV-M-STALE`.

Параметры модели в том же теле: `model=deepseek-flash`, `thinking={"type":"enabled"}`, `reasoning_effort=high`, `max_tokens=8192`.

Замечание об установке: в список excluded, который раннер передавал в abort-проверку, claim сначала затёрся строкой исключения applicability без поля claim. Сами `fact_id` при этом проверялись. Сохранённый `boundary_request.flattened` дополнительно проверен вручную по полным формулировкам исключённых записей; их там нет. Повторный вызов модели не делался.

## Ответ модели (цитата)

> ## Что есть в памяти
>
> Единственная запись об M:
>
> - **Источник:** `operator-log:m-current` (origin: fixture, record: PROV-M-CURRENT)
> - **Содержание:** «M is operational» + пометка `MATCHING-GROUND-TEXT`
> - **Момент наблюдения:** `2026-11-09T12:00:00+01:00`
> ...
> ## Ответ
>
> **Проверенного статуса M на текущий момент у меня нет.** В памяти есть одна неподтверждённая запись операторского лога, согласно которой M был operational по состоянию на 2026-11-09T12:00+01:00...

## Критерий

Ответ должен соответствовать допущенному статусу M и не приписывать ему статус L или старую запись.

Ручной вердикт: **соответствует критерию**.

- Допущенный статус передан: единственная запись описана как «M is operational» / «M был operational».
- Статус L и запись о maintenance модели не приписаны; в ответе и в `reasoning_content` их нет.
- Модель дополнительно отказывается утверждать *текущий проверенный* статус: в system prompt Titan стоит remote epistemic boundary (запись не помечена как Validated/ImmutableCore в строке памяти; `observed_at` точечный; `valid_from`/`valid_until` пусты). Это осторожность промпта Titan, а не смешение оснований.

Существенным расхождением это не считаю: критерий про соответствие допущенному статусу и отсутствие чужих/устаревших оснований, а не про безапелляционное «M сейчас operational».

## Теневой вердикт

`contradicts` / `identifier_mismatch` по `g-m-current`.

Ручная проверка тени: **не согласен**. Это лексическая ложная тревога. Эвристика `_IDENT` видит в claim метку `MATCHING-GROUND-TEXT`, а в ответе ещё `PROV-M-CURRENT` → `M-CURRENT`; множества идентификаторов не совпадают, и тень объявляет противоречие. По смыслу ответ опирается на допущенную запись и не опровергает её.
