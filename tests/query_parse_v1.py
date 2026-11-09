"""Rule-based parser: ordinary Russian status questions -> explicit filter parameters.

Experiment (Crystal-Test lab). Pure functions: no I/O, no server clock, no
machine timezone, no model calls, stdlib only. The parser decides only WHAT
the user asked (object + moment). It never reads, writes or annotates
evidence: facts keep exactly their persisted applicability declarations, so a
question about L can never turn an L2 document into evidence about L.

Output is one of three kinds:

* ``parsed``              -- ``params`` (asked_object, as_of, temporal_scope)
                             plus ``explanation`` of where each came from;
* ``needs_clarification`` -- one concrete question to the user;
* ``unsupported``         -- a clear limitation message.

Only ``parsed`` may reach the filter (see :func:`ask`). Ambiguity or failure is
never turned into a query with an omitted (= disabled) object or time filter:
``parsed`` always carries a non-empty asked_object, temporal_scope="current"
and a valid explicit as_of.

Mapping onto the accepted #503 contract (unchanged): temporal_scope="current"
with as_of=T asks for the state *at T*. Admitted grounds are facts whose
validity interval covers T (date-only bounds are whole inclusive days) or
whose observation is exactly T at the same precision; earlier observations are
historical-only. So "сейчас" -> as_of = the explicit now instant; a past moment
"8 ноября в 10:00" -> as_of = that instant in the explicit timezone; a bare
day ("сегодня", "8 ноября") -> a date-only as_of, i.e. the whole day must be
covered. Periods, changes, comparisons, history, event times and future
moments are not expressible as one point and are ``unsupported``.
"""
import re
from datetime import date, datetime, time, timedelta, timezone as _utc_mod, tzinfo
from typing import Any, Dict, Iterable, List, Optional, Sequence

try:  # stdlib; tz database may be absent on some platforms
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9 is not supported by the lab
    ZoneInfo = None  # type: ignore

MAX_CONTEXT_TURNS = 3
SCOPE = "current"

_TOKEN = re.compile(r"[A-Za-zА-Яа-яЁё0-9]+(?:[-_][A-Za-zА-Яа-яЁё0-9]+)*")
_IDENT_LIKE = re.compile(r"^(?:[A-Z][A-Z0-9_-]{0,7}|[A-Z]+\d+[A-Z0-9]*)$")
_INFLECTIONS = ("а", "у", "ом", "е", "ы", "ов", "ами", "ах", "и", "я", "ю", "ем")
_PRONOUNS = {"его", "него", "нему", "ним", "нём", "нем", "он"}
_FOLLOW_UP_STARTS = {"а", "и"}

_MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}

_NOW_PATTERNS = (r"\bсейчас\b", r"\bна данный момент\b", r"\bв данный момент\b",
                 r"\bтекущ\w*\b", r"\bтеперь\b")
_PERIOD_PATTERNS = (
    (r"\bза\s+(?:вчера|сегодня|позавчера|неделю|месяц|день|год|период|последн\w*|прошл\w*|\d+)",
     "вопрос о периоде («за …»)"),
    (r"\bс\s+\d{1,2}\b.*\bпо\s+\d{1,2}\b", "вопрос о периоде («с … по …»)"),
    (r"\bмежду\b", "вопрос о периоде («между …»)"),
    (r"\bв течени[еи]\b", "вопрос о периоде («в течение …»)"),
    (r"\bнедел\w*|\bмесяц\w*", "вопрос о периоде (неделя/месяц)"),
    (r"\bменял\w*|\bизмен\w*|\bдинамик\w*", "вопрос об изменениях"),
    (r"\bсравн\w*", "сравнение"),
    (r"\bистори\w*", "история статусов"),
    (r"\bкогда\b", "вопрос о времени события («когда …»)"),
    (r"\bбудет\b|\bзавтра\b|\bпослезавтра\b", "вопрос о будущем (прогноз)"),
)
_VAGUE_PARTS = r"\b(?:утром|днём|днем|вечером|ночью)\b"
_STATUS = r"\bстатус\w*|\bсостояни\w*"


def _result_unsupported(limitation: str, **extra) -> Dict[str, Any]:
    return {"kind": "unsupported", "limitation": limitation, **extra}


def _result_clarify(question: str, reason: str, candidates: Sequence[str] = ()) -> Dict[str, Any]:
    return {"kind": "needs_clarification", "question": question, "reason": reason,
            "candidates": list(candidates)}


def _tokens(text: str):
    return [(m.group(0), m.start(), m.end()) for m in _TOKEN.finditer(text)]


def _alias_index(known_objects: Iterable[Dict[str, Any]]):
    """casefolded alias -> set(object ids). Shared aliases are kept as collisions."""
    index: Dict[tuple, set] = {}
    for obj in known_objects:
        oid = obj.get("id")
        if not isinstance(oid, str) or not oid.strip():
            continue
        names = [oid] + [n for n in obj.get("names", []) if isinstance(n, str)]
        for name in names:
            key = tuple(t.casefold() for t, _, _ in _tokens(name))
            if key:
                index.setdefault(key, set()).add(oid.strip())
    return index


def _token_matches(token: str, alias_token: str) -> bool:
    t = token.casefold()
    if t == alias_token:
        return True
    # Light inflection only for Cyrillic word-like aliases (e.g. «Пульсара»).
    if len(alias_token) >= 4 and re.fullmatch(r"[а-яё]+", alias_token):
        return any(t == alias_token + ending for ending in _INFLECTIONS)
    return False


def _mentions(tokens, index):
    """Longest-match object mentions: [{'ids','alias','pos','negated'}]."""
    found, i = [], 0
    keys = sorted(index, key=len, reverse=True)
    while i < len(tokens):
        hit = None
        for key in keys:
            n = len(key)
            if i + n <= len(tokens) and all(_token_matches(tokens[i + j][0], key[j]) for j in range(n)):
                hit = key
                break
        if hit:
            negated = i > 0 and tokens[i - 1][0].casefold() == "не"
            found.append({"ids": sorted(index[hit]), "alias": " ".join(t[0] for t in tokens[i:i + len(hit)]),
                          "pos": i, "negated": negated})
            i += len(hit)
        else:
            i += 1
    return found


def _resolve_tz(tz_value) -> Optional[tzinfo]:
    if isinstance(tz_value, tzinfo):
        return tz_value
    if isinstance(tz_value, str) and tz_value.strip() and ZoneInfo is not None:
        try:
            return ZoneInfo(tz_value.strip())
        except Exception:  # unknown/invalid zone name
            return None
    return None


def _local(day: date, clock: time, tz: tzinfo):
    """Return an aware datetime, or None for nonexistent/ambiguous local times (DST)."""
    naive = datetime.combine(day, clock)
    first, second = naive.replace(tzinfo=tz, fold=0), naive.replace(tzinfo=tz, fold=1)
    if first.utcoffset() != second.utcoffset():
        return None  # ambiguous (DST fall-back) or nonexistent (spring-forward)
    if first.astimezone(_utc_mod.utc).astimezone(tz).replace(tzinfo=None) != naive:
        return None  # pragma: no cover - covered by the offset check for real zones
    return first


def _parse_clock(low: str):
    """Return (time, token) or None. Only explicit clock forms."""
    m = re.search(r"\b(\d{1,2}):(\d{2})\b", low)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        return (time(h, mi), m.group(0)) if h < 24 and mi < 60 else ("invalid", m.group(0))
    m = re.search(r"\bв\s+(\d{1,2})\s+(час\w*|утра|дня|вечера|ночи)\b", low)
    if m:
        h, word = int(m.group(1)), m.group(2)
        if word in ("дня", "вечера") and 1 <= h <= 11:
            h += 12
        if word == "ночи" and h == 12:
            h = 0
        return (time(h, 0), m.group(0)) if h < 24 else ("invalid", m.group(0))
    return None


def _parse_day(low: str, now_local: Optional[datetime]):
    """Return dict(kind, day, token, year_source) or None or {'error':...}."""
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", low)
    if m:
        try:
            return {"day": date(int(m.group(1)), int(m.group(2)), int(m.group(3))),
                    "token": m.group(0), "year_source": "указан в вопросе"}
        except ValueError:
            return {"error": "некорректная дата «%s»" % m.group(0)}
    m = re.search(r"\b(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?\b", low)
    if not m:
        m2 = re.search(r"\b(\d{1,2})\s+(%s)(?:\s+(\d{4})(?:\s+года?)?)?" % "|".join(_MONTHS), low)
        if m2:
            d, mo, y = int(m2.group(1)), _MONTHS[m2.group(2)], m2.group(3)
            token = m2.group(0)
        else:
            d = mo = y = token = None
    else:
        d, mo, y, token = int(m.group(1)), int(m.group(2)), m.group(3), m.group(0)
    if token is not None:
        if y is None:
            if now_local is None:
                return {"error": "no_clock"}
            year, src = now_local.year, "год взят из явно заданного текущего момента (%d)" % now_local.year
        else:
            year, src = int(y), "указан в вопросе"
        try:
            return {"day": date(year, mo, d), "token": token, "year_source": src, "year_inferred": y is None}
        except ValueError:
            return {"error": "некорректная дата «%s»" % token}
    for word, delta in (("сегодня", 0), ("вчера", -1)):
        if re.search(r"\b%s\b" % word, low):
            if now_local is None:
                return {"error": "no_clock"}
            return {"day": now_local.date() + timedelta(days=delta), "token": word,
                    "year_source": "относительно явно заданного текущего момента"}
    return None


def _time_reference(low: str, now: Optional[datetime], tz: Optional[tzinfo]):
    """Return {'ref': 'now'|'absolute'|'date', 'as_of', 'why'} or a result dict, or None if no time words."""
    has_now = any(re.search(p, low) for p in _NOW_PATTERNS)
    # Year/relative-day arithmetic uses the explicit zone; without a zone the
    # explicit now offset is used only to detect date words, then we clarify.
    now_local = (now.astimezone(tz) if tz is not None else now) if now is not None else None
    clock = _parse_clock(low)
    day = _parse_day(low, now_local)
    vague = re.search(_VAGUE_PARTS, low)
    if has_now and (day or clock):
        return _result_clarify("Вы спрашиваете о статусе сейчас или на указанный момент?",
                               "в вопросе одновременно «сейчас» и конкретная дата/время")
    if has_now:
        if now is None:
            return _result_unsupported("нет явно заданного текущего момента: «сейчас» не берётся из часов сервера")
        as_of = (now.astimezone(tz) if tz is not None else now).isoformat()
        return {"ref": "now", "as_of": as_of,
                "why": "«сейчас»-форма в вопросе → as_of = явно заданный текущий момент %s" % as_of}
    if day is None and clock is None:
        if vague:
            return _result_clarify("На какое время именно? Укажите час, например «в 10:00».",
                                   "часть суток («%s») не является моментом" % vague.group(0))
        return None
    if day is not None and "error" in day:
        if day["error"] == "no_clock":
            return _result_unsupported("для дат без года и для «сегодня/вчера» нужен явно заданный текущий момент и часовой пояс")
        return _result_clarify("Уточните дату: %s." % day["error"], day["error"])
    if clock == "invalid" or (isinstance(clock, tuple) and clock[0] == "invalid"):
        return _result_clarify("Уточните время: «%s» не является временем суток." % clock[1], "некорректное время")
    if day is None:
        return _result_clarify("Какого дня это время (%s)?" % clock[1], "время указано без даты")
    if vague and clock is None:
        return _result_clarify("На какое время %s? Укажите час, например «в 10:00»." % day["token"],
                               "часть суток («%s») не является моментом" % vague.group(0))
    if tz is None:
        return _result_clarify("В каком часовом поясе считать «%s»?" % (day["token"] + (" " + clock[1] if clock else "")),
                               "часовой пояс не задан явно")
    if now is None:
        return _result_unsupported("нет явно заданного текущего момента: нельзя проверить, что момент не в будущем")
    if clock is None:
        if day["day"] > now_local.date():
            if day.get("year_inferred"):
                return _result_clarify("Какой год вы имеете в виду для «%s»?" % day["token"],
                                       "в текущем году эта дата ещё не наступила")
            return _result_unsupported("вопрос о будущем дне: прогноз статуса не поддерживается")
        as_of = day["day"].isoformat()
        return {"ref": "date", "as_of": as_of,
                "why": "день «%s» без времени → date-only as_of %s (весь день в поясе %s; %s)"
                       % (day["token"], as_of, tz, day["year_source"])}
    moment = _local(day["day"], clock[0], tz)
    if moment is None:
        return _result_clarify("Местное время %s %s неоднозначно или не существует (переход на летнее/зимнее время). Уточните смещение UTC."
                               % (day["token"], clock[1]), "DST")
    if moment > now:
        if day.get("year_inferred"):
            return _result_clarify("Какой год вы имеете в виду для «%s»?" % day["token"],
                                   "в текущем году этот момент ещё не наступил")
        return _result_unsupported("вопрос о будущем моменте: прогноз статуса не поддерживается")
    as_of = moment.isoformat()
    return {"ref": "absolute", "as_of": as_of,
            "why": "«%s» + «%s» в явно заданном поясе %s → as_of %s (%s)"
                   % (day["token"], clock[1], tz, as_of, day["year_source"])}


def _bounded(context) -> List[Dict[str, Any]]:
    turns = [t for t in (context or []) if isinstance(t, dict)]
    return turns[-MAX_CONTEXT_TURNS:]


def parse_question(question: str, known_objects: Sequence[Dict[str, Any]],
                   context: Optional[Sequence[Dict[str, Any]]] = None, *,
                   now: Optional[datetime] = None, timezone: Any = None) -> Dict[str, Any]:
    """Parse one question. See module docstring for the contract.

    known_objects: [{"id": "L", "names": ["L", "Л"]}, ...]
    context: prior structured turns (output of :func:`context_turn`), newest
      last; only the last MAX_CONTEXT_TURNS are considered and old text is
      never re-parsed.
    now: explicit aware datetime (never the server clock).
    timezone: explicit IANA name or tzinfo (never the machine timezone).
    """
    if not isinstance(question, str) or not question.strip():
        return _result_clarify("Сформулируйте, пожалуйста, вопрос.", "пустой вопрос")
    if now is not None and (not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None):
        return _result_unsupported("текущий момент должен быть явным datetime с часовым поясом")
    tz = _resolve_tz(timezone)
    if timezone is not None and tz is None:
        return _result_unsupported("часовой пояс «%s» не распознан" % (timezone,))
    text = question.strip()
    low = text.casefold()

    for pattern, label in _PERIOD_PATTERNS:
        if re.search(pattern, low):
            return _result_unsupported(
                "Первая версия разбирает только статус одного объекта на один момент; %s не поддерживается." % label)

    tokens = _tokens(text)
    words = [t[0].casefold() for t in tokens]
    index = _alias_index(known_objects)
    mentions = _mentions(tokens, index)
    positive = [m for m in mentions if not m["negated"]]
    covered = {m["pos"] for m in mentions}
    unknown = [t[0] for i, t in enumerate(tokens) if i not in covered and _IDENT_LIKE.match(t[0])]
    has_pronoun = any(w in _PRONOUNS for w in words)
    follow_up = bool(words) and words[0] in _FOLLOW_UP_STARTS
    status_words = bool(re.search(_STATUS, low))
    known_ids = sorted({i for ids in index.values() for i in ids})
    explanation: Dict[str, str] = {}
    from_context = None

    # ── object ────────────────────────────────────────────────────────────
    if positive:
        ids = sorted({i for m in positive for i in m["ids"]})
        if len(positive) > 1 and len(ids) > 1 or unknown:
            cands = ids + unknown
            return _result_clarify("О каком объекте вопрос: %s? Первая версия отвечает про один объект." % ", ".join(cands),
                                   "упомянуто несколько объектов", cands)
        if len(ids) > 1:
            return _result_clarify("Название «%s» подходит к нескольким объектам: %s. Какой из них?"
                                   % (positive[0]["alias"], ", ".join(ids)), "коллизия названий", ids)
        asked = ids[0]
        neg = [m["alias"] for m in mentions if m["negated"]]
        explanation["asked_object"] = ("название «%s» → объект %s" % (positive[0]["alias"], asked)
                                       + ("; исключено по отрицанию: %s" % ", ".join(neg) if neg else "")
                                       + ("; местоимение относится к нему же в этой реплике" if has_pronoun else ""))
    elif unknown:
        return _result_clarify("Объект «%s» неизвестен. О каком объекте вопрос? Известные: %s." % (unknown[0], ", ".join(known_ids)),
                               "неизвестный объект", known_ids)
    elif has_pronoun or follow_up:
        decided = None
        turns = _bounded(context)
        for offset, turn in enumerate(reversed(turns), start=1):
            if turn.get("kind") == "parsed" and isinstance(turn.get("asked_object"), str):
                decided = ("object", turn, offset)
                break
            if turn.get("candidates"):
                decided = ("ambiguous", turn, offset)
                break
        if decided is None:
            return _result_clarify("О каком объекте вы спрашиваете? Известные: %s." % ", ".join(known_ids),
                                   "в ограниченном контексте (последние %d реплики) нет однозначного объекта" % MAX_CONTEXT_TURNS,
                                   known_ids)
        kind, turn, offset = decided
        if kind == "ambiguous":
            cands = list(turn["candidates"])
            return _result_clarify("Уточните, о каком объекте: %s?" % ", ".join(cands),
                                   "предыдущая реплика не определила объект однозначно", cands)
        asked = turn["asked_object"]
        from_context = turn
        explanation["asked_object"] = "из контекста: %d-я реплика с конца («%s») → объект %s" % (
            offset, turn.get("question", ""), asked)
    else:
        return _result_clarify("О каком объекте вы спрашиваете? Известные: %s." % ", ".join(known_ids),
                               "объект не назван", known_ids)

    if not status_words and from_context is None and not follow_up:
        return _result_unsupported("Первая версия разбирает только вопросы о статусе/состоянии объекта.")

    # ── time ──────────────────────────────────────────────────────────────
    ref = _time_reference(low, now, tz)
    if isinstance(ref, dict) and ref.get("kind"):
        return ref
    if ref is None:
        prior = from_context if from_context is not None else (
            _bounded(context)[-1] if follow_up and _bounded(context) else None)
        prior_ref = prior.get("time_ref") if prior and prior.get("kind") == "parsed" else None
        if prior_ref == "now":
            if now is None:
                return _result_unsupported("нет явно заданного текущего момента")
            as_of = (now.astimezone(tz) if tz is not None else now).isoformat()
            ref = {"ref": "now", "as_of": as_of,
                   "why": "время не названо; предыдущая реплика спрашивала «сейчас» → заново привязано к явно заданному текущему моменту %s" % as_of}
        elif prior_ref in ("absolute", "date") and isinstance(prior.get("as_of"), str):
            ref = {"ref": prior_ref, "as_of": prior["as_of"],
                   "why": "время не названо; унаследовано из предыдущей реплики: as_of %s" % prior["as_of"]}
        else:
            return _result_clarify("На какой момент: сейчас или на конкретную дату и время?",
                                   "время не указано; без него фильтр времени не включается, а молча его не выключаем")
    params = {"asked_object": asked, "as_of": ref["as_of"], "temporal_scope": SCOPE}
    explanation["as_of"] = ref["why"]
    explanation["temporal_scope"] = ("'current' = состояние на момент as_of по контракту #503 "
                                     "(допускаются факты, чей интервал покрывает as_of или наблюдение ровно в as_of)")
    return {"kind": "parsed", "params": params, "time_ref": ref["ref"], "explanation": explanation}


def context_turn(question: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """Structured, bounded memory of one turn for later follow-ups."""
    turn = {"question": question, "kind": result.get("kind")}
    if result.get("kind") == "parsed":
        turn.update(asked_object=result["params"]["asked_object"], time_ref=result["time_ref"],
                    as_of=result["params"]["as_of"])
    elif result.get("candidates"):
        turn["candidates"] = list(result["candidates"])
    return turn


def ask(question: str, known_objects, context=None, *, now=None, timezone=None, query_fn,
        query_text: Optional[str] = None) -> Dict[str, Any]:
    """Gate: only a ``parsed`` result may call the status query.

    ``needs_clarification`` / ``unsupported`` run nothing and return no answer,
    so a parse failure can never become an unfiltered current-status answer.
    """
    from core.applicability import request_error  # pure validation, no I/O

    parse = parse_question(question, known_objects, context, now=now, timezone=timezone)
    if parse["kind"] != "parsed":
        return {"parse": parse, "query_called": False, "answer": None}
    params = parse["params"]
    if (not params.get("asked_object") or params.get("temporal_scope") != SCOPE
            or request_error(**params) is not None):  # pragma: no cover - defense in depth
        raise AssertionError("parser produced an incomplete filter request")
    result = query_fn(query_text if query_text is not None else question, **params)
    return {"parse": parse, "query_called": True, "answer": result.get("answer"), "result": result}
