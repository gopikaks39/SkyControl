"""Controller-pilot communication safety: readback verification and callsign similarity.

Gap addressed: most air-ground communication is still voice. Readback errors
(the pilot repeats a value wrongly), hearback errors (the controller misses
the wrong readback) and callsign confusion (an aircraft with a similar callsign
takes an instruction meant for another) are long-standing causes of incidents.

SkyControl structures every clearance, sends it digitally where possible and,
for voice, parses the pilot's readback (typed or speech-to-text transcript)
and compares it field by field with what was issued. It also scores callsign
similarity for every pair of aircraft on the same frequency.
"""
from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Clearances
# ---------------------------------------------------------------------------

FIELD_ORDER = ('level', 'heading', 'speed', 'direct', 'squawk', 'frequency', 'qnh', 'runway')
READBACK_REQUIRED = set(FIELD_ORDER)   # ICAO Doc 4444 safety-related items

WORDS = {
    'zero': '0', 'one': '1', 'two': '2', 'three': '3', 'tree': '3', 'four': '4', 'fower': '4',
    'five': '5', 'fife': '5', 'six': '6', 'seven': '7', 'eight': '8', 'nine': '9', 'niner': '9',
}
SPOKEN = {v: k for k, v in WORDS.items() if k not in ('tree', 'fower', 'fife', 'nine')}
SPOKEN['9'] = 'niner'
# Radiotelephony designators used by the operators most common in the recording.
TELEPHONY = {
    'speedbird': 'BAW', 'easy': 'EZY', 'ryanair': 'RYR', 'shamrock': 'EIN', 'klm': 'KLM', 'lufthansa': 'DLH',
    'swiss': 'SWR', 'tomson': 'TOM', 'jet2': 'EXS', 'channex': 'EXS', 'shuttle': 'SHT', 'cityflyer': 'CFE',
    'virgin': 'VIR', 'qatari': 'QTR', 'emirates': 'UAE', 'cathay': 'CPA', 'alpine': 'EJU', 'topswiss': 'EZS',
    'ryanair uk': 'RUK', 'wizz go': 'WUK', 'american': 'AAL', 'delta': 'DAL', 'united': 'UAL', 'airfrans': 'AFR',
}


@dataclass
class Clearance:
    callsign: str
    level: int | None = None          # feet; flight levels stored as FL*100
    heading: int | None = None
    speed: int | None = None
    direct: str | None = None
    squawk: str | None = None
    frequency: str | None = None
    qnh: int | None = None
    runway: str | None = None
    extra: dict = field(default_factory=dict)

    def fields(self):
        return {k: getattr(self, k) for k in FIELD_ORDER if getattr(self, k) is not None}


def _digits(value, width=0):
    s = str(value).zfill(width) if width else str(value)
    return ' '.join(SPOKEN.get(c, 'decimal' if c == '.' else c) for c in s)


def level_text(level, transition_altitude=6000):
    if level > transition_altitude:
        return f'flight level {_digits(level // 100, 3)}'
    thousands, hundreds = divmod(level, 1000)
    words = f'{_digits(thousands)} thousand'
    if hundreds:
        words += f' {_digits(hundreds // 100)} hundred'
    return words + ' feet'


def telephony(callsign):
    """Spoken form of an ICAO callsign, e.g. BAW425 -> Speedbird four two five."""
    prefix, suffix = split_callsign(callsign)
    word = next((w for w, d in TELEPHONY.items() if d == prefix and ' ' not in w), None)
    if not word:
        return callsign
    return word.capitalize() + ' ' + ' '.join(SPOKEN.get(ch, NATO_SPOKEN.get(ch, ch)) for ch in suffix)


def phraseology(c: Clearance, current_level=None):
    """Render a clearance in ICAO-style phraseology."""
    parts = [telephony(c.callsign)]
    if c.level is not None:
        verb = 'climb' if current_level is not None and c.level > current_level else 'descend' if current_level is not None else 'climb'
        parts.append(f'{verb} {level_text(c.level)}')
    if c.heading is not None:
        parts.append(f'turn heading {_digits(c.heading, 3)}')
    if c.speed is not None:
        parts.append(f'speed {_digits(c.speed)} knots')
    if c.direct:
        parts.append(f'proceed direct {c.direct}')
    if c.squawk:
        parts.append(f'squawk {_digits(c.squawk, 4)}')
    if c.qnh is not None:
        parts.append(f'QNH {_digits(c.qnh)}')
    if c.runway:
        number, side = c.runway[:2], c.runway[2:]
        parts.append(f"runway {_digits(number)}" + {'L': ' left', 'R': ' right', 'C': ' centre'}.get(side, ''))
    if c.frequency:
        parts.append(f'contact {_digits(c.frequency)}')
    return ', '.join(parts)


# ---------------------------------------------------------------------------
# Readback parsing
# ---------------------------------------------------------------------------

NATO = {'alpha': 'a', 'alfa': 'a', 'bravo': 'b', 'charlie': 'c', 'echo': 'e', 'foxtrot': 'f', 'golf': 'g',
        'hotel': 'h', 'india': 'i', 'juliett': 'j', 'juliet': 'j', 'kilo': 'k', 'lima': 'l', 'mike': 'm',
        'november': 'n', 'oscar': 'o', 'papa': 'p', 'quebec': 'q', 'romeo': 'r', 'sierra': 's', 'tango': 't',
        'uniform': 'u', 'victor': 'v', 'whiskey': 'w', 'xray': 'x', 'yankee': 'y', 'zulu': 'z'}
NATO_SPOKEN = {v.upper(): k for k, v in NATO.items() if k not in ('alfa', 'juliet')}
FILLERS = {'the', 'to', 'and', 'uh', 'roger', 'wilco', 'say', 'again', 'via'}
AIRLINE_CODES = set(TELEPHONY.values())
SIDES = {'left': 'L', 'right': 'R', 'centre': 'C', 'center': 'C', 'l': 'L', 'r': 'R', 'c': 'C'}
LEVEL_VERBS = ('climb', 'climbing', 'descend', 'descending', 'maintain', 'maintaining', 'altitude')


def tokens(text: str):
    """Lower-case word tokens with every digit as its own token ('.' kept for decimals)."""
    t = text.lower()
    for word in sorted(TELEPHONY, key=len, reverse=True):
        t = re.sub(rf'\b{word}\b', TELEPHONY[word].lower(), t)
    t = re.sub(r'\bfl(?=\s*\d)', 'flight level ', t)
    # Punctuation and gaps between typed numbers are boundaries a digit group must not cross.
    t = re.sub(r'[,;]|(?<=\d)\s+(?=\d)|\.(?!\d)', ' | ', t)
    out = []
    for tok in re.findall(r'[a-z]+|\d|\.|\|', t):
        tok = WORDS.get(tok, NATO.get(tok, tok))
        out.append('.' if tok in ('decimal', 'point') else tok)
    return out


def normalise(text: str) -> str:
    """Readable normalised form: spoken digits as numerals, digit runs joined."""
    out = []
    for tok in tokens(text):
        if tok == '|':
            out.append(',')
        elif (tok.isdigit() or tok == '.') and out and re.fullmatch(r'[\d.]+', out[-1]):
            out[-1] += tok
        else:
            out.append(tok)
    return ' '.join(out).replace(' ,', ',').strip(', ')


class _Reader:
    """Cursor over the token list that consumes digit groups of a known length."""

    def __init__(self, toks):
        self.toks = toks
        self.used = [False] * len(toks)
        self.raw = {}

    def digits_after(self, i, min_n, max_n):
        k, out = i, ''
        while k < len(self.toks) and self.toks[k].isdigit() and len(out) < max_n and not self.used[k]:
            out += self.toks[k]
            k += 1
        if len(out) < min_n:
            return None, i
        for m in range(i, k):
            self.used[m] = True
        return out, k

    def find(self, *words):
        for i, tok in enumerate(self.toks):
            if tok in words:
                return i
        return -1


def _parse_level(r: _Reader):
    toks = r.toks
    for i in range(len(toks) - 1):
        if toks[i] == 'flight' and toks[i + 1] == 'level':
            value, _ = r.digits_after(i + 2, 2, 3)
            if value:
                r.raw['level'] = value
                return int(value) * 100
    for i, tok in enumerate(toks):
        if tok not in LEVEL_VERBS:
            continue
        k = i + 1
        while k < len(toks) and toks[k] in ('to', 'and', 'maintain', 'altitude'):
            k += 1
        value, k = r.digits_after(k, 1, 5)
        if not value:
            continue
        r.raw['level'] = value
        number = int(value)
        if k < len(toks) and toks[k] == 'thousand':
            number *= 1000
            k += 1
            hundreds, k2 = r.digits_after(k, 1, 1)
            if hundreds and k2 < len(toks) and toks[k2] == 'hundred':
                number += int(hundreds) * 100
        elif k < len(toks) and toks[k] == 'hundred':
            number *= 100
        return number
    # Bare altitude: "6000 feet", "six thousand feet".
    for i, tok in enumerate(toks):
        if tok in ('feet', 'ft') and i > 0:
            k = i - 1
            if toks[k] == 'thousand':
                k -= 1
            start = k
            while start > 0 and toks[start - 1].isdigit() and not r.used[start - 1]:
                start -= 1
            value, end = r.digits_after(start, 1, 5)
            if value:
                r.raw['level'] = value
                return int(value) * (1000 if end < len(toks) and toks[end] == 'thousand' else 1)
    return None


def parse_readback(text: str, known_callsigns=()):
    """Extract clearance fields from a readback (typed or speech-to-text)."""
    r = _Reader(tokens(text))
    toks = r.toks
    found = {}
    # The callsign digits are consumed first so they are not mistaken for values.
    found['callsign'] = identify_callsign(text, known_callsigns)
    if found['callsign']:
        prefix, suffix = split_callsign(found['callsign'])
        i = r.find((prefix or '').lower())
        if i >= 0:
            for k in range(i + 1, min(len(toks), i + 1 + len(suffix))):
                if toks[k].isdigit() or len(toks[k]) == 1:
                    r.used[k] = True
    level = _parse_level(r)
    if level is not None:
        found['level'] = level
    for key, words, lo, hi in (('heading', ('heading',), 2, 3), ('speed', ('speed',), 2, 3),
                               ('squawk', ('squawk', 'squawking'), 4, 4), ('qnh', ('qnh',), 3, 4)):
        i = r.find(*words)
        if i >= 0:
            value, _ = r.digits_after(i + 1, lo, hi)
            if value:
                r.raw[key] = value
                found[key] = value if key == 'squawk' else int(value)
    if 'heading' in found:
        found['heading'] = found['heading'] % 360 or 360
    i = r.find('direct')
    if i >= 0:
        k = i + 1 + (i + 1 < len(toks) and toks[i + 1] == 'to')
        if k < len(toks) and toks[k].isalpha() and 2 <= len(toks[k]) <= 5 and toks[k] not in FILLERS \
                and toks[k].upper() not in AIRLINE_CODES:
            found['direct'] = toks[k].upper()
        else:
            found['_unclear'] = found.get('_unclear', []) + ['direct']
    i = r.find('runway')
    if i >= 0:
        value, k = r.digits_after(i + 1, 1, 2)
        if value:
            side = SIDES.get(toks[k], '') if k < len(toks) else ''
            found['runway'] = value.zfill(2) + side
    # Frequency: three digits, optional decimal, one to three digits, among the unused tokens.
    free = ''.join(t if (t.isdigit() or t == '.') and not used else ' ' for t, used in zip(toks, r.used))
    m = re.search(r'(1[1-3]\d)\.?(\d{1,3})', free)
    if m:
        found['frequency'] = f"{m.group(1)}.{m.group(2)}".rstrip('0').rstrip('.')
        r.raw['frequency'] = m.group(1) + m.group(2)
    found['_raw'] = r.raw
    return found


def _spoken_digits(key, value):
    """Digits a pilot would say for an issued value (used to recognise dropped digits)."""
    if key == 'level':
        return str(value // 100) if value > 6000 else str(value).rstrip('0') or '0'
    if key == 'heading':
        return f'{value:03d}'
    if key == 'frequency':
        return re.sub(r'\D', '', str(value)).ljust(4, '0')
    return re.sub(r'\D', '', str(value))


def _is_subsequence(short, long):
    it = iter(long)
    return all(ch in it for ch in short)


def identify_callsign(text, known_callsigns):
    """Best-matching known callsign mentioned in the transmission (or None)."""
    compact = re.sub(r'[^a-z0-9]', '', normalise(text).replace(' ', '')).upper()
    best = None
    for cs in known_callsigns:
        key = cs.upper()
        if key in compact:
            if best is None or len(key) > len(best):
                best = key
    return best


def verify_readback(clearance: Clearance, readback: str, frequency_callsigns=()):
    """Compare a readback with the issued clearance.

    Returns a verdict with one entry per issued field. Verdicts:
    CORRECT, INCOMPLETE (a required item not read back), MISMATCH (a value
    differs), WRONG_AIRCRAFT (another aircraft on frequency answered).
    """
    known = set(frequency_callsigns) | {clearance.callsign}
    heard = parse_readback(readback, known)
    issued = clearance.fields()
    items, mismatches, missing = [], [], []
    for key, value in issued.items():
        got = heard.get(key)
        if got is None and key in heard.get('_unclear', []):
            status = 'unclear'
            missing.append(key)
        elif got is None:
            status = 'missing' if key in READBACK_REQUIRED else 'not required'
            if key in READBACK_REQUIRED:
                missing.append(key)
        elif str(got).upper() == str(value).upper() or (key == 'frequency' and float(got) == float(value)) \
                or (key == 'runway' and str(got).upper().lstrip('0') == str(value).upper().lstrip('0')):
            status = 'match'
        else:
            raw = heard['_raw'].get(key)
            expected = _spoken_digits(key, value)
            implausible = key == 'level' and got < 500     # e.g. "climb five feet": the word "thousand" was lost
            if implausible or (raw and len(raw) < len(expected) and _is_subsequence(raw, expected)):
                # Digits were lost (speech recognition or clipped transmission): uncertain, not wrong.
                status = 'unclear'
                missing.append(key)
            else:
                status = 'mismatch'
                mismatches.append(key)
        items.append({'field': key, 'issued': value, 'read_back': got, 'status': status})
    answering = heard.get('callsign')
    if answering and answering != clearance.callsign.upper():
        verdict = 'WRONG_AIRCRAFT'
    elif mismatches:
        verdict = 'MISMATCH'
    elif missing:
        verdict = 'INCOMPLETE'
    else:
        verdict = 'CORRECT'
    advice = {
        'CORRECT': 'Readback matches the clearance. No action needed.',
        'MISMATCH': 'Readback differs from the clearance: ' + ', '.join(mismatches) + '. Correct immediately ("negative, I say again ...").',
        'INCOMPLETE': 'Required items not heard clearly in the readback: ' + ', '.join(missing) + '. Ask the crew to confirm.',
        'WRONG_AIRCRAFT': f'{answering} answered an instruction for {clearance.callsign}. Possible callsign confusion: cancel and re-issue to both aircraft.',
    }[verdict]
    return {'verdict': verdict, 'severity': SEVERITY[verdict], 'items': items, 'answering_callsign': answering,
            'normalised_readback': normalise(readback), 'advice': advice}


SEVERITY = {'CORRECT': 'none', 'INCOMPLETE': 'confirm', 'MISMATCH': 'error', 'WRONG_AIRCRAFT': 'error'}


# ---------------------------------------------------------------------------
# Callsign similarity
# ---------------------------------------------------------------------------

def split_callsign(cs: str):
    m = re.match(r'^([A-Z]{3})([0-9A-Z]+)$', cs.strip().upper())
    return (m.group(1), m.group(2)) if m else (None, cs.strip().upper())


def callsign_similarity(a: str, b: str):
    """Similarity score 0-1 and the reason, following the patterns that cause confusion."""
    a, b = a.strip().upper(), b.strip().upper()
    if not a or not b or a == b:
        return 0.0, None
    pa, sa = split_callsign(a)
    pb, sb = split_callsign(b)
    if pa is None or pb is None:
        return 0.0, None
    same_operator = pa == pb
    if same_operator and sorted(sa) == sorted(sb):
        return 0.95, 'same characters in a different order'
    if same_operator and len(sa) == len(sb) and sum(x != y for x, y in zip(sa, sb)) == 1:
        return 0.9, 'one character differs'
    if same_operator and len(sa) >= 3 and len(sb) >= 3 and sa[-2:] == sb[-2:]:
        return 0.75, 'same final characters'
    if same_operator and len(sa) >= 3 and len(sb) >= 3 and sa[:3] == sb[:3]:
        return 0.7, 'same leading characters'
    if not same_operator and sa == sb:
        return 0.6, 'same flight number, different operator'
    if same_operator and abs(len(sa) - len(sb)) == 1 and (sa in sb or sb in sa):
        return 0.65, 'one character added or dropped'
    return 0.0, None


def similar_pairs(callsigns, threshold=0.6):
    out = []
    for a, b in itertools.combinations(sorted(set(c for c in callsigns if c)), 2):
        score, reason = callsign_similarity(a, b)
        if score >= threshold:
            out.append({'a': a, 'b': b, 'score': score, 'reason': reason})
    return sorted(out, key=lambda r: -r['score'])
