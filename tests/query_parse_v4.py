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

v2 (after review of d550f3f): explicitly expressed user constraints are never
dropped. A time zone named in the question is used only from a closed list
(Москва / Берлин / UTC); any other zone-like wording -> clarification. Several
time expressions or alternatives ("в 10:00 или в 12:00", "7 или 8 ноября") ->
clarification, never the first match. A short alias inside a near-matching
longer multi-word alias -> clarification, and multi-word aliases are inflected
word by word. Every result records ``mentioned_objects`` so a later pronoun
cannot silently skip an object mentioned in an unsupported/clarified turn.
The frozen v1 is kept at ``tests/query_parse_v1.py`` for evidence.

v3 (after review of eee4062; frozen v2 at ``tests/query_parse_v2.py``):
* zone/place detection is case-insensitive («по Лондону» = «по лондону» =
  «ПО ЛОНДОНУ» -> clarification);
* the clock is parsed whole: seconds are kept exactly; fractional seconds,
  minute/second words, «половина/четверть/полдень/полночь», «в 10.00» and ISO
  «…T10:00» -> clarification; a day part after a clock («10:30 вечера», «в 10
  часов вечера») is applied, conflicting combinations -> clarification;
* object choice does not depend on catalogue order: all aliases matching at a
  position are collected, then ranked (1) longest span, (2) exact name over
  match via inflection; a tie between different objects -> clarification.

v4 (user rule change 2026-11-09; frozen v3 at ``tests/query_parse_v3.py``):
* step (2) is removed: if one word form matches two objects — one directly and
  one via inflection — BOTH stay candidates and the user is asked, unless the
  bounded context holds a confirmed choice among them with no later conflicting
  mention (then that choice is used, explained); conflicting context -> ask;
* an explicit identifier («объект M», «объекта Y», «(объект M)») selects that
  object when every other mention in the question is compatible with it and
  the mentions are not joined by «и/или/либо»; otherwise ask;
* a bare answer to an object clarification («M», «объект M») is a confirmed
  choice: it answers the clarified question when that question had a usable
  time (stored structurally as ``pending_time``), otherwise asks for the time;
  ``confirmed_object`` is kept in the structured context.
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
# Light per-word inflection of Cyrillic alias words (v2): (alias ending, endings
# replacing it). Applied to every word of a multi-word alias («Главный мост» ->
# «Главного моста»). Not a morphological analyser; unknown forms do not match.
_ADJ_ENDINGS = ("ый", "ий", "ой", "ого", "его", "ому", "ему", "ым", "им", "ом", "ем", "ые", "ие", "ых", "их",
                "ыми", "ими", "ая", "яя", "ую", "юю", "ей", "ое", "ее")
_FEM_ENDINGS = ("а", "я", "ы", "и", "е", "у", "ю", "ой", "ей", "ою", "ам", "ами", "ах")
_SOFT_ENDINGS = ("ь", "я", "ю", "ем", "е", "и", "ей", "ям", "ями", "ях")
_NEAR_PREFIX = 4  # a neighbouring word sharing this many first letters with a longer alias word is a near miss
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

# Closed list of time zones that may be named inside a question (v2).
_NAMED_ZONES = (
    (r"\bпо\s+московскому\s+времени\b|\bпо\s+москве\b|\bмск\b|\bmsk\b", "Europe/Moscow"),
    (r"\bпо\s+берлинскому\s+времени\b|\bпо\s+берлину\b", "Europe/Berlin"),
    (r"\bпо\s+utc\b|\butc\b", "UTC"),
)
# Anything zone-like that is not exactly one closed-list phrase -> clarification.
_ZONE_LIKE = (
    r"\bпо\s+[а-яё]+(?:ому|ему)\s+времени\b",
    r"\bпо\s+времени\b",
    r"\bпо\s+гринвичу\b",
    r"\bчасов\w*\s+пояс\w*|\bпояс\w*",
    r"\b(?:utc|gmt|мск|msk|cet|cest|eet|eest|wet|west|est|edt|cst|cdt|mst|mdt|pst|pdt|bst|jst)\b",
    r"\b(?:utc|gmt|мск|msk)\s*[+\-−]\s*\d{1,2}(?::?\d{2})?",
    r"\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:[+\-−]\d{1,2}(?::?\d{2})?|z)\b",
)
# v3: case-insensitive «по <word>» place detection on the casefolded text. A word
# after «по» is treated as a possible place/zone unless it is an object alias, a
# pronoun or starts with one of these non-place stems («по статусу», «по
# состоянию на», «по данным», «по умолчанию» …) -> unknown places clarify.
_PO_WORD = re.compile(r"\bпо\s+([a-zа-яё][a-zа-яё0-9]*)")
_PO_NOT_PLACE = ("статус", "состояни", "данн", "информаци", "документ", "источник", "факт", "отчёт", "отчет",
                 "итог", "сут", "существ", "дел", "правил", "умолчани", "ошибк", "причин", "запрос", "вопрос",
                 "мнени", "оценк", "смысл", "поводу", "порядк")
_TIME_ALTERNATIVE = r"\b\d{1,2}(?::\d{2})?\s+(?:или|либо|и)\s+(?:в\s+|на\s+)?\d{1,2}\b"
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


def _stem_endings(alias_token: str):
    if re.search(r"(?:ый|ий|ой|ая|яя|ое|ее)$", alias_token):
        return alias_token[:-2], _ADJ_ENDINGS
    if alias_token[-1] in "ая":
        return alias_token[:-1], _FEM_ENDINGS
    if alias_token[-1] == "ь":
        return alias_token[:-1], _SOFT_ENDINGS
    return alias_token, _INFLECTIONS


def _token_matches(token: str, alias_token: str) -> bool:
    t = token.casefold()
    if t == alias_token:
        return True
    # Light inflection only for Cyrillic word-like alias words (e.g. «Пульсара»,
    # and, in v2, each word of «Главный мост» -> «Главного моста»).
    if len(alias_token) >= 4 and re.fullmatch(r"[а-яё]+", alias_token):
        stem, endings = _stem_endings(alias_token)
        return any(t == stem + ending for ending in endings)
    return False


def _near(token: str, alias_token: str) -> bool:
    t = token.casefold()
    n = min(_NEAR_PREFIX, len(alias_token))
    return len(t) >= n and t[:n] == alias_token[:n]


def _near_misses(tokens, index, mentions):
    """Short alias found where a LONGER alias containing it nearly matches the
    neighbouring words (e.g. «Главнейшего моста» vs «Главный мост» / «Мост")."""
    out = []
    for m in mentions:
        for key in m["keys"]:
            for longer, ids in index.items():
                if len(longer) <= len(key) or set(ids) == set(m["ids"]):
                    continue
                for j in range(len(longer) - len(key) + 1):
                    if longer[j:j + len(key)] != key:
                        continue
                    start = m["pos"] - j
                    end = start + len(longer)
                    if start < 0 or end > len(tokens):
                        continue
                    others = [k for k in range(len(longer)) if not j <= k < j + len(key)]
                    if all(_near(tokens[start + k][0], longer[k]) for k in others):
                        out.append({"short": m, "longer_ids": sorted(ids),
                                    "longer": " ".join(longer)})
    # v3: deterministic regardless of catalogue order
    return sorted(out, key=lambda n: (n["longer"], n["longer_ids"], n["short"]["pos"]))


_EXACT, _INFLECTED = 2, 1


def _match_rank(tokens, i, key) -> int:
    """_EXACT if every word equals the alias word (casefolded), _INFLECTED if some
    word matches only via the ending table, 0 if no match."""
    if i + len(key) > len(tokens):
        return 0
    rank = _EXACT
    for j, alias_word in enumerate(key):
        t = tokens[i + j][0].casefold()
        if t == alias_word:
            continue
        if not _token_matches(t, alias_word):
            return 0
        rank = _INFLECTED
    return rank


def _mentions(tokens, index, text=""):
    """Object mentions, independent of catalogue order (v3).

    At each position ALL matching aliases are collected first, then resolved:
    (1) the longest span wins (it covers more of the user's words);
    (2) among equally long spans an exact name beats a match via inflection;
    (3) every object left at the top tier is kept in ``ids`` -> more than one
        id is an unresolvable collision (the caller asks for clarification).
    v4: step (2) removed — see module docstring; per-id match type in ``how``.
    Returns [{'ids','alias','pos','len','negated','keys','how','explicit_id','match'}].
    """
    found, i = [], 0
    while i < len(tokens):
        hits = [(len(key), _match_rank(tokens, i, key), key) for key in index]
        hits = [h for h in hits if h[1]]
        if hits:
            # v4: only the span length ranks; exact vs inflection no longer decides
            n = max(h[0] for h in hits)
            top = sorted(key for k, r, key in hits if k == n)
            how = {}
            for k, r, key in sorted(hits, key=lambda h: (h[1], h[2])):  # exact (2) after inflection (1): exact wins per id
                if k == n:
                    for oid in index[key]:
                        how[oid] = ("exact" if r == _EXACT else "inflection", " ".join(key))
            ids = sorted(how)
            negated = i > 0 and tokens[i - 1][0].casefold() == "не"
            explicit = None
            if n == 1 and tokens[i][0] in ids:  # identifier written exactly as the object id
                prev_word = tokens[i - 1][0].casefold() if i > 0 else ""
                before = text[:tokens[i][1]].rstrip()
                if prev_word.startswith("объект") or before.endswith("("):
                    explicit = tokens[i][0]
            found.append({"ids": ids, "alias": " ".join(t[0] for t in tokens[i:i + n]), "pos": i, "len": n,
                          "negated": negated, "keys": top, "how": how, "explicit_id": explicit,
                          "match": "exact" if all(v[0] == "exact" for v in how.values()) else "inflection"})
            i += n
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


def _zone_in_text(text: str, low: str, alias_words) -> Dict[str, Any]:
    """Zone named in the question: {} (none), {'zone','tz','phrase','spans'} or {'clarify': result}."""
    found, spans = {}, []
    for pattern, name in _NAMED_ZONES:
        for m in re.finditer(pattern, low):
            found.setdefault(name, m.group(0))
            spans.append(m.span())
    unknown = []
    for pattern in _ZONE_LIKE:
        for m in re.finditer(pattern, low):
            if not any(a <= m.start() and m.end() <= b for a, b in spans):
                unknown.append(m.group(0))
                spans.append(m.span())
    for m in _PO_WORD.finditer(low):
        word = m.group(1)
        if (any(a <= m.start() and m.end() <= b for a, b in spans) or any(_token_matches(word, w) for w in alias_words)
                or word in _PRONOUNS or word.startswith(_PO_NOT_PLACE)):
            continue
        unknown.append(m.group(0))
        spans.append(m.span())
    if unknown:
        return {"spans": spans, "clarify": _result_clarify(
            "В вопросе указан часовой пояс или место («%s»), который первая версия не разбирает. "
            "Уточните момент по Москве, по Берлину или в UTC." % unknown[0],
            "часовой пояс назван в тексте, но не входит в закрытый список (Москва, Берлин, UTC)")}
    if len(found) > 1:
        return {"spans": spans, "clarify": _result_clarify(
            "В вопросе названо несколько часовых поясов (%s). По какому считать?" % ", ".join(found.values()),
            "несколько часовых поясов", sorted(found))}
    if found:
        name, phrase = next(iter(found.items()))
        return {"zone": name, "tz": ZoneInfo(name) if ZoneInfo is not None else None, "phrase": phrase, "spans": spans}
    return {"spans": spans}


_DAY_PART = r"утра|дня|вечера|ночи"
_CLOCK_COLON = re.compile(r"(?<![\d:.,])(\d{1,2}):(\d{2})(?::(\d{2}))?([.,]\d+)?(?![\d:])(?:\s*(%s)\b)?" % _DAY_PART)
_CLOCK_WORD = re.compile(r"\bв\s+(\d{1,2})\s+(?:час\w*(?:\s+(%s))?|(%s))\b" % (_DAY_PART, _DAY_PART))
_CLOCK_PATTERNS = (_CLOCK_COLON.pattern, _CLOCK_WORD.pattern)
# v3: clock forms that carry more (or other) precision than we parse -> clarification, never truncation
_PRECISION_WORDS = r"\bминут\w*|\bсекунд\w*|\bполовин\w*|\bчетверт\w*|\bполдень\b|\bполудн\w*|\bполночь\b|\bполуноч\w*"
_ISO_T = r"\b\d{4}-\d{2}-\d{2}t[\d:.,+\-z]+"
_DOTTED_CLOCK = r"\bв\s+\d{1,2}\.\d{2}\b(?!\.\d)"
_DAY_PATTERNS = (r"\b\d{4}-\d{2}-\d{2}\b", r"\b\d{1,2}\.\d{1,2}(?:\.\d{4})?\b",
                 r"\b\d{1,2}\s+(?:%s)\b" % "|".join(_MONTHS), r"\b(?:сегодня|вчера|позавчера)\b")


def _spans(patterns, low):
    # The clock patterns (and the day patterns) cannot overlap each other.
    return sorted((m.start(), m.end(), m.group(0)) for pattern in patterns for m in re.finditer(pattern, low))


def _blank(low: str, spans) -> str:
    for a, b, _ in spans:
        low = low[:a] + " " * (b - a) + low[b:]
    return low


def _several_moments(low: str):
    """v2: several clocks, several days, or a numeric alternative -> the list of expressions.
    v3: day patterns are searched outside clock spans (so «10:00:30.5» is one clock)."""
    clocks = _spans(_CLOCK_PATTERNS, low)
    days = _spans(_DAY_PATTERNS, _blank(low, clocks))
    alt = re.search(_TIME_ALTERNATIVE, low)
    if len(clocks) > 1 or len(days) > 1 or alt:
        exprs = list(dict.fromkeys(t for _, _, t in sorted(clocks + days)))
        if alt and len(clocks) < 2 and len(days) < 2:
            exprs.append(alt.group(0))
        return exprs
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


def _apply_day_part(h: int, part: Optional[str]) -> Optional[int]:
    """24h hour for «h <part>», or None when the combination is not unambiguous."""
    if part is None:
        return h
    if part == "утра":
        return h if 0 <= h <= 11 else None
    if part == "дня":
        return h + 12 if 1 <= h <= 5 else h if 12 <= h <= 17 else None
    if part == "вечера":
        return h + 12 if 5 <= h <= 11 else h if 17 <= h <= 23 else None
    # «ночи»
    return 0 if h == 12 else h if 0 <= h <= 4 or 21 <= h <= 23 else h + 12 if 9 <= h <= 11 else None


def _parse_clock(low: str):
    """Return (time, token), ('invalid'|'precision'|'day_part', token) or None.

    v3: the clock is parsed whole (hours, minutes, optional seconds kept
    exactly); fractional seconds -> 'precision'; a following day part is applied.
    """
    m = _CLOCK_COLON.search(low)
    if m:
        h, mi, sec, frac, part = int(m.group(1)), int(m.group(2)), m.group(3), m.group(4), m.group(5)
        token = m.group(0)
        if frac:
            return ("precision", token)
        sec = int(sec) if sec is not None else 0
        if not (h < 24 and mi < 60 and sec < 60):
            return ("invalid", token)
        hh = _apply_day_part(h, part)
        return (time(hh, mi, sec), token) if hh is not None else ("day_part", token)
    m = _CLOCK_WORD.search(low)
    if m:
        h, part = int(m.group(1)), m.group(2) or m.group(3)
        if h >= 24:
            return ("invalid", m.group(0))
        hh = _apply_day_part(h, part)
        return (time(hh, 0), m.group(0)) if hh is not None else ("day_part", m.group(0))
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
    several = _several_moments(low)
    # Year/relative-day arithmetic uses the explicit zone; without a zone the
    # explicit now offset is used only to detect date words, then we clarify.
    now_local = (now.astimezone(tz) if tz is not None else now) if now is not None else None
    clock = _parse_clock(low)
    day = _parse_day(_blank(low, _spans(_CLOCK_PATTERNS, low)), now_local)
    vague = re.search(_VAGUE_PARTS, low)
    if has_now and (day or clock):
        return _result_clarify("Вы спрашиваете о статусе сейчас или на указанный момент?",
                               "в вопросе одновременно «сейчас» и конкретная дата/время")
    form = (re.search(_PRECISION_WORDS, low) or re.search(_ISO_T, low) or re.search(_DOTTED_CLOCK, low))
    if form or (isinstance(clock, tuple) and clock[0] == "precision"):
        token = form.group(0) if form else clock[1]
        return _result_clarify("Форма или точность времени «%s» не поддерживается; укажите время как ЧЧ:ММ или ЧЧ:ММ:СС "
                               "(например «10:00:30») и дату отдельно." % token,
                               "время разбирается целиком; другая точность не усекается")
    if isinstance(clock, tuple) and clock[0] == "day_part":
        return _result_clarify("Уточните время «%s»: часть суток не согласуется с часом. Укажите ЧЧ:ММ в 24-часовом формате."
                               % clock[1], "противоречивая часть суток")
    if several:
        return _result_clarify("В вопросе несколько моментов или вариантов (%s). На какой один момент ответить?"
                               % ", ".join("«%s»" % e for e in several),
                               "несколько выражений времени или альтернатива; первое совпадение не считается выбором пользователя")
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


_CHOICE_FILLERS = {"объект", "объекта", "это", "да", "вот", "конечно", "я", "имею", "в", "виду", "про", "нужен", "нужна"}
_JOINERS = {"и", "или", "либо"}


def _confirmed_in_context(context, cands):
    """v4: newest confirmed choice among ``cands`` in the bounded context.

    Returns ('ok', obj, turn, offset), ('conflict', objs) when a newer turn asked
    about / mentioned another candidate, or None."""
    seen = set()
    for offset, turn in enumerate(reversed(_bounded(context)), start=1):
        c = turn.get("confirmed_object")
        if isinstance(c, str) and c in cands:
            return ("ok", c, turn, offset) if seen <= {c} else ("conflict", sorted(seen | {c}))
        objs = {o for o in turn.get("mentioned_objects") or [] if isinstance(o, str)}
        if turn.get("kind") == "parsed" and isinstance(turn.get("asked_object"), str):
            objs.add(turn["asked_object"])
        seen |= objs & set(cands)
    return None


def _describe(m):
    return ", ".join("%s (%s «%s»)" % (oid, "точное название" if m["how"][oid][0] == "exact" else "через склонение",
                                       m["how"][oid][1]) for oid in m["ids"])


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
    tokens = _tokens(text)
    index = _alias_index(known_objects)
    mentions = _mentions(tokens, index, text)
    # v2: record every positively mentioned known object, whatever the outcome.
    mentioned = sorted({i for m in mentions if not m["negated"] for i in m["ids"]})
    result = _parse(text, low, tokens, index, mentions, context, now, tz, timezone)
    if mentioned:
        result["mentioned_objects"] = mentioned
    return result


def _parse(text, low, tokens, index, mentions, context, now, tz, timezone_param):
    for pattern, label in _PERIOD_PATTERNS:
        if re.search(pattern, low):
            return _result_unsupported(
                "Первая версия разбирает только статус одного объекта на один момент; %s не поддерживается." % label)

    words = [t[0].casefold() for t in tokens]
    alias_words = {w for key in index for w in key}
    zone = _zone_in_text(text, low, alias_words)
    zone_spans = zone["spans"]
    positive = [m for m in mentions if not m["negated"]]
    covered = {m["pos"] + k for m in mentions for k in range(m["len"])}
    unknown = [t[0] for i, t in enumerate(tokens) if i not in covered and _IDENT_LIKE.match(t[0])
               and not any(a <= t[1] and t[2] <= b for a, b in zone_spans)]  # «UTC» is a zone, not an object
    has_pronoun = any(w in _PRONOUNS for w in words)
    follow_up = bool(words) and words[0] in _FOLLOW_UP_STARTS
    status_words = bool(re.search(_STATUS, low))
    known_ids = sorted({i for ids in index.values() for i in ids})
    explanation: Dict[str, str] = {}
    from_context = None

    def time_part(fc):
        return _parse_time_part(low, now, tz, zone, context, follow_up, fc)

    def finish(asked, fc):
        tp = time_part(fc)
        if tp[0] == "result":
            return tp[1]
        _, ref, zone_note, _zone_name = tp
        params = {"asked_object": asked, "as_of": ref["as_of"], "temporal_scope": SCOPE}
        explanation["as_of"] = ref["why"] + ("; " + zone_note if zone_note else "")
        explanation["temporal_scope"] = ("'current' = состояние на момент as_of по контракту #503 "
                                         "(допускаются факты, чей интервал покрывает as_of или наблюдение ровно в as_of)")
        return {"kind": "parsed", "params": params, "time_ref": ref["ref"], "explanation": explanation}

    # ── v4: bare answer to an object clarification = confirmed choice ──────
    turns_ctx = _bounded(context)
    last = turns_ctx[-1] if turns_ctx else None
    if (last and last.get("kind") == "needs_clarification" and last.get("candidates") and len(positive) == 1
            and not [m for m in mentions if m["negated"]] and not unknown
            and all(i in covered or words[i] in _CHOICE_FILLERS for i in range(len(tokens)))):
        offered = [c for c in last["candidates"] if isinstance(c, str)]
        chosen = sorted(set(positive[0]["ids"]) & set(offered))
        if len(chosen) != 1:
            cands = chosen or offered
            return _result_clarify("«%s» %s. Выберите один из вариантов: %s." % (
                positive[0]["alias"], "не среди предложенных вариантов" if not chosen else "подходит нескольким вариантам",
                ", ".join(cands)), "ответ на уточнение не выбирает ровно один из предложенных объектов", cands)
        x = chosen[0]
        pend = last.get("pending_time") if isinstance(last.get("pending_time"), dict) else None
        expl = {"asked_object": "подтверждённый выбор пользователя: ответ «%s» на уточнение к «%s» (варианты %s) → объект %s"
                                % (text, last.get("question", ""), ", ".join(offered), x)}
        if pend and pend.get("time_ref") == "now":
            if now is None:
                return _result_unsupported("нет явно заданного текущего момента")
            ptz = _resolve_tz(pend.get("tz")) or tz
            as_of = (now.astimezone(ptz) if ptz is not None else now).isoformat()
            why = "уточнённая реплика спрашивала «сейчас» → заново привязано к явно заданному текущему моменту %s" % as_of
        elif pend and pend.get("time_ref") in ("absolute", "date") and isinstance(pend.get("as_of"), str):
            as_of, why = pend["as_of"], "момент из уточнённой реплики: as_of %s" % pend["as_of"]
        else:
            r = _result_clarify("Выбран объект %s. На какой момент: сейчас или на конкретную дату и время?" % x,
                                "в уточнённой реплике не было пригодного момента")
            r["confirmed_object"] = x
            return r
        expl["as_of"] = why
        expl["temporal_scope"] = ("'current' = состояние на момент as_of по контракту #503 "
                                  "(допускаются факты, чей интервал покрывает as_of или наблюдение ровно в as_of)")
        return {"kind": "parsed", "params": {"asked_object": x, "as_of": as_of, "temporal_scope": SCOPE},
                "time_ref": pend["time_ref"], "explanation": expl, "confirmed_object": x}

    # ── object ────────────────────────────────────────────────────────────
    explicit = sorted({m["explicit_id"] for m in positive if m.get("explicit_id")})
    if positive and explicit:
        ids = sorted({i for m in positive for i in m["ids"]})
        first = min(m["pos"] for m in positive)
        end = max(m["pos"] + m["len"] for m in positive)
        joined = any(words[k] in _JOINERS for k in range(first, end))
        if len(explicit) > 1 or unknown or joined or any(explicit[0] not in m["ids"] for m in positive):
            cands = sorted(set(ids) | set(explicit)) + unknown
            return _result_clarify("О каком объекте вопрос: %s? Явный идентификатор не согласуется с остальными упоминаниями."
                                   % ", ".join(cands), "явный идентификатор и другие упоминания расходятся", cands)
        asked = explicit[0]
        others = [m["alias"] for m in positive if m.get("explicit_id") != asked]
        neg = [m["alias"] for m in mentions if m["negated"]]
        explanation["asked_object"] = ("явный идентификатор «объект %s» → объект %s" % (asked, asked)
                                       + ("; согласуется с названием «%s»" % "», «".join(others) if others else "")
                                       + ("; исключено по отрицанию: %s" % ", ".join(neg) if neg else ""))
    elif positive:
        ids = sorted({i for m in positive for i in m["ids"]})
        if len(positive) > 1 and len(ids) > 1 or unknown:
            cands = ids + unknown
            return _result_clarify("О каком объекте вопрос: %s? Первая версия отвечает про один объект." % ", ".join(cands),
                                   "упомянуто несколько объектов", cands)
        resolved = None
        if len(ids) > 1:
            ctx_choice = _confirmed_in_context(context, ids)
            if ctx_choice and ctx_choice[0] == "ok":
                resolved = ctx_choice
            else:
                if ctx_choice:  # conflict
                    r = _result_clarify("Форма «%s» подходит к нескольким объектам: %s. Ранее был подтверждён выбор, но затем "
                                        "упоминался другой из них (%s). Какой из них?"
                                        % (positive[0]["alias"], _describe(positive[0]), ", ".join(ctx_choice[1])),
                                        "контекст противоречив: подтверждённый выбор и более позднее упоминание", ids)
                else:
                    r = _result_clarify("Форма «%s» подходит к нескольким объектам: %s. Какой из них?"
                                        % (positive[0]["alias"], _describe(positive[0])), "коллизия названий", ids)
                pend = time_part(None)
                if pend[0] == "ref":
                    r["pending_time"] = {"time_ref": pend[1]["ref"], "as_of": pend[1]["as_of"], "tz": pend[3]}
                return r
        if resolved:
            _, asked, turn, offset = resolved
            explanation["asked_object"] = ("форма «%s» подходит к нескольким объектам: %s; выбор %s подтверждён пользователем "
                                           "(%d-я реплика с конца, «%s»), противоречащих упоминаний после него нет"
                                           % (positive[0]["alias"], _describe(positive[0]), asked, offset, turn.get("question", "")))
            return finish(asked, None)
        near = _near_misses(tokens, index, positive)
        if near:
            n = near[0]
            cands = sorted(set(ids).union(*(x["longer_ids"] for x in near)))
            return _result_clarify("Вы имеете в виду «%s» (%s) или «%s» (%s)?"
                                   % (n["longer"], ", ".join(n["longer_ids"]), n["short"]["alias"], ", ".join(ids)),
                                   "короткое название внутри почти совпавшего составного названия; не подменяем одно другим",
                                   cands)
        asked = ids[0]
        neg = [m["alias"] for m in mentions if m["negated"]]
        how = [m for m in positive if asked in m["ids"]][0]
        explanation["asked_object"] = ("название «%s» → объект %s" % (positive[0]["alias"], asked)
                                       + (" (точное совпадение названия)" if how["how"][asked][0] == "exact"
                                          else " (совпадение через склонение)")
                                       + ("; исключено по отрицанию: %s" % ", ".join(neg) if neg else "")
                                       + ("; местоимение относится к нему же в этой реплике" if has_pronoun else ""))
    elif unknown:
        return _result_clarify("Объект «%s» неизвестен. О каком объекте вопрос? Известные: %s." % (unknown[0], ", ".join(known_ids)),
                               "неизвестный объект", known_ids)
    elif has_pronoun or follow_up:
        decided = None
        pending = set()  # v2: objects mentioned by later non-parsed turns (possible switch)
        turns = _bounded(context)
        for offset, turn in enumerate(reversed(turns), start=1):
            if turn.get("kind") == "parsed" and isinstance(turn.get("asked_object"), str):
                decided = ("object", turn, offset)
                break
            if isinstance(turn.get("confirmed_object"), str):  # v4: confirmed choice without a time
                decided = ("object", dict(turn, asked_object=turn["confirmed_object"]), offset)
                break
            if turn.get("candidates"):
                decided = ("ambiguous", turn, offset)
                break
            pending |= {o for o in turn.get("mentioned_objects") or [] if isinstance(o, str)}
        if pending and (decided is None or decided[0] == "ambiguous" or not pending <= {decided[1]["asked_object"]}):
            prior = set(decided[1]["asked_object"] if decided[0] == "object" else decided[1]["candidates"]) if decided else set()
            cands = sorted(pending | prior)
            return _result_clarify("Уточните, о каком объекте: %s? После последнего разобранного вопроса упоминался другой объект."
                                   % ", ".join(cands),
                                   "возможная смена объекта: неразобранная реплика упоминала %s" % ", ".join(sorted(pending)),
                                   cands)
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
            offset, turn.get("question", ""), asked) + (
            "; промежуточные реплики упоминали только этот объект" if pending else "")
    else:
        return _result_clarify("О каком объекте вы спрашиваете? Известные: %s." % ", ".join(known_ids),
                               "объект не назван", known_ids)

    if not status_words and from_context is None and not follow_up:
        return _result_unsupported("Первая версия разбирает только вопросы о статусе/состоянии объекта.")
    return finish(asked, from_context)


def _parse_time_part(low, now, tz, zone, context, follow_up, from_context):
    """Time section. Returns ('result', dict) or ('ref', ref, zone_note, zone_name)."""
    if "clarify" in zone:
        return ("result", zone["clarify"])
    zone_note = None
    if zone.get("zone"):
        if zone["tz"] is None:  # pragma: no cover - tz database absent
            return ("result", _result_clarify("Часовой пояс «%s» недоступен; уточните смещение UTC." % zone["phrase"],
                                              "нет базы поясов"))
        default = tz
        tz = zone["tz"]
        zone_note = "часовой пояс назван в вопросе («%s») → %s" % (zone["phrase"], zone["zone"]) + (
            "; заданный по умолчанию пояс %s не используется" % default
            if default is not None and str(default) != zone["zone"] else "")
    ref = _time_reference(low, now, tz)
    if isinstance(ref, dict) and ref.get("kind"):
        return ("result", ref)
    prior = from_context if from_context is not None else (
        _bounded(context)[-1] if follow_up and _bounded(context) else None)
    if ref is None and zone_note:
        if prior and prior.get("time_ref") in ("absolute", "date"):
            return ("result", _result_clarify(
                "Пересчитать прежний момент в поясе «%s» или вы имеете в виду другой момент?" % zone["phrase"],
                "пояс назван без момента; прежний момент был в другом поясе"))
    if ref is None:
        prior_ref = prior.get("time_ref") if prior and prior.get("kind") == "parsed" else None
        if prior_ref == "now":
            if now is None:
                return ("result", _result_unsupported("нет явно заданного текущего момента"))
            as_of = (now.astimezone(tz) if tz is not None else now).isoformat()
            ref = {"ref": "now", "as_of": as_of,
                   "why": "время не названо; предыдущая реплика спрашивала «сейчас» → заново привязано к явно заданному текущему моменту %s" % as_of}
        elif prior_ref in ("absolute", "date") and isinstance(prior.get("as_of"), str):
            ref = {"ref": prior_ref, "as_of": prior["as_of"],
                   "why": "время не названо; унаследовано из предыдущей реплики: as_of %s" % prior["as_of"]}
        else:
            return ("result", _result_clarify("На какой момент: сейчас или на конкретную дату и время?",
                                              "время не указано; без него фильтр времени не включается, а молча его не выключаем"))
    return ("ref", ref, zone_note, zone.get("zone"))


def context_turn(question: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """Structured, bounded memory of one turn for later follow-ups."""
    turn = {"question": question, "kind": result.get("kind")}
    if result.get("kind") == "parsed":
        turn.update(asked_object=result["params"]["asked_object"], time_ref=result["time_ref"],
                    as_of=result["params"]["as_of"])
    elif result.get("candidates"):
        turn["candidates"] = list(result["candidates"])
        if isinstance(result.get("pending_time"), dict):  # v4: time of the clarified question, structured
            turn["pending_time"] = dict(result["pending_time"])
    if result.get("confirmed_object"):  # v4: user's confirmed choice
        turn["confirmed_object"] = result["confirmed_object"]
    if result.get("kind") != "parsed" and result.get("mentioned_objects"):
        turn["mentioned_objects"] = list(result["mentioned_objects"])  # v2: possible object switch
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
