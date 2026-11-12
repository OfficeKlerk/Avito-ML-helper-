"""BM25 over an already authorized corpus. No labels or prepared answers at runtime."""

from __future__ import annotations

import math
import re
import threading
import unicodedata
from collections import Counter
from functools import lru_cache

import snowballstemmer

from .models import Chunk

K1, B = 1.5, 0.75
MIN_COVERAGE = 0.6
# Snowball по-разному режет формы одного глагола: «настроить» → настро, «настрой» → настр,
# «поднять» → подня, «подними» → подн. Основы, которые отличаются одной буквой на конце, считаем одним словом.
# Две буквы уже опасно: «стендап» → стендап и «стенды» → стенд — разные слова.
MIN_FORM_LENGTH = 4
NEAR_FORM_WEIGHT = 0.9
TOKENS = re.compile(r"[a-zа-я0-9]+")
THREAD = threading.local()
STOPWORDS = frozenset("""а без бы был была были было быть в вам вас ваш ваша ваши во вот все всего всем вы
где да для до его ее если есть еще же за зачем здесь и из или им их к как какая
какие каким каких какой когда кого ком кому который кто куда сколько ли мне мной моем
мой моя мы на надо нас нам нами наш наша наши него нее ней нем нет ни но ну о об один он она
они оно от по под пожалуйста пока после при про с сам себе со так такая такие
такой там тебе тем то того тоже только том ту ты у уже чего чем что чтобы эта
эти этим это этот я расскажи расскажите скажи подскажи подскажите можно нужно
нужен нужна нужны хочу получить делать сделать оформить оформлять запросить
сегодня завтра ближайший ближайшую работает рабочий работу работаю
правило правила правил инструкция инструкции инструкцию порядок оформление
""".split())
ALIASES = {
    "standup": "стендап", "daily": "стендап", "дейли": "стендап",
    "дейлик": "стендап", "гитлаб": "gitlab", "джира": "jira",
    "конфлюенс": "confluence", "впн": "vpn", "онбординг": "адаптац",
    "ментор": "наставник", "release": "релиз", "rollback": "откат",
}


@lru_cache(maxsize=8192)
def _stem(word: str) -> str:
    # Snowball objects are mutable: one per thread, never shared concurrently.
    if not hasattr(THREAD, "russian"):
        THREAD.russian = snowballstemmer.stemmer("russian")
    return THREAD.russian.stemWord(word)


STEMMED_STOPWORDS = frozenset(_stem(word) for word in STOPWORDS)


def tokenize(text: str, *, enhanced: bool = True) -> list[str]:
    text = unicodedata.normalize("NFKC", text).casefold().replace("ё", "е")
    text = re.sub(r"\b1\s*:\s*1\b", "oneonone", text)
    words = TOKENS.findall(text)
    if not enhanced:
        return words
    stems = (_stem(ALIASES.get(word, word)) for word in words if word not in STOPWORDS)
    return [stem for stem in stems if stem not in STEMMED_STOPWORDS]


class SearchIndex:
    """Immutable after construction; DF/length statistics see permitted chunks only."""

    def __init__(self, chunks: tuple[Chunk, ...], *, enhanced: bool = True):
        self.chunks, self.enhanced = chunks, enhanced
        self.frequencies, lengths, headings, df = [], [], [], Counter()
        for chunk in chunks:
            body = tokenize(chunk.text, enhanced=enhanced)
            heading = tokenize(chunk.section, enhanced=enhanced)
            headings.append(frozenset(heading))
            title = tokenize(chunk.document.title, enhanced=enhanced)
            tags = tokenize(" ".join(chunk.document.tags), enhanced=enhanced)
            words = body + heading * (3 if enhanced else 1) + title * (2 if enhanced else 1) + tags
            counts = Counter(words)
            self.frequencies.append(counts)
            lengths.append(len(words))
            df.update(counts.keys())
        self.frequencies = tuple(self.frequencies)
        self.lengths = tuple(lengths)
        self.heading_terms = tuple(headings)
        self.average_length = sum(lengths) / len(lengths) if lengths else 1.0
        self.idf = {word: math.log1p((len(chunks) - count + 0.5) / (count + 0.5)) for word, count in df.items()}

    def forms(self, term: str) -> dict[str, float]:
        """Основы из словаря, которые считаем тем же словом, с весом: точное совпадение — 1."""
        found = {term: 1.0} if term in self.idf else {}
        if self.enhanced and len(term) >= MIN_FORM_LENGTH:
            for word in self.idf:
                shorter, longer = sorted((term, word), key=len)
                if len(longer) == len(shorter) + 1 and len(shorter) >= MIN_FORM_LENGTH and longer.startswith(shorter):
                    found.setdefault(word, NEAR_FORM_WEIGHT)
        return found

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        query, top_k = validate_request({"query": query, "top_k": top_k})
        terms = frozenset(tokenize(query, enhanced=self.enhanced))
        if not terms:
            return []
        forms = {term: self.forms(term) for term in terms}
        scored = []
        for chunk, counts, length, heading in zip(self.chunks, self.frequencies, self.lengths, self.heading_terms):
            norm = K1 * (1 - B + B * length / self.average_length)
            # Для каждого слова запроса — лучшая из его форм в этом фрагменте.
            best = {}
            for term in sorted(terms):
                options = [weight * self.idf[w] * counts[w] * (K1 + 1) / (counts[w] + norm)
                           for w, weight in forms[term].items() if w in counts]
                if options:
                    best[term] = max(options)
            coverage = len(best) / len(terms)
            if not best or (self.enhanced and coverage < MIN_COVERAGE):
                continue
            score = sum(best[t] for t in sorted(best))
            if self.enhanced:
                # Prefer a section explicitly about the query, not just a shared document tag.
                in_heading = sum(1 for t in terms if heading.intersection(forms[t]))
                score *= coverage * (1 + in_heading / len(terms))
            scored.append((score, chunk))
        scored.sort(key=lambda item: (-item[0], item[1].chunk_id))
        return [chunk.to_result(score) for score, chunk in scored[:top_k]]


def validate_request(body) -> tuple[str, int]:
    if not isinstance(body, dict) or set(body) - {"query", "top_k"}:
        raise ValueError("invalid search request")
    query, top_k = body.get("query"), body.get("top_k", 5)
    if not isinstance(query, str) or not query.strip() or len(query) > 1000:
        raise ValueError("invalid query")
    if isinstance(top_k, bool) or not isinstance(top_k, (int, float)) or not 1 <= top_k <= 10 or top_k != int(top_k):
        raise ValueError("invalid top_k")
    return query, int(top_k)
