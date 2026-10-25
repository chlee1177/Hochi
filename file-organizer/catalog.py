"""Persistent local metadata and offline search. Raw document text is not stored."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import sqlite3
import unicodedata


def terms(text):
    words = re.findall(r'[a-z0-9]+|[가-힣]+', unicodedata.normalize('NFKC', text).lower())
    ignored = {'관련', '자료', '문서', '파일', '찾아줘', '보여줘', '찾아주세요', '보여주세요', '대한'}
    result = set()
    for word in words:
        if word in ignored:
            continue
        result.add(word)
        if re.fullmatch('[가-힣]+', word):
            result.update(word[i:i + 2] for i in range(len(word) - 1))
    return result


def searchable(record):
    return ' '.join([record['current_path'], record.get('folder', ''), record.get('summary', ''), *record.get('tags', [])])


class Catalog:
    def __init__(self, path):
        self.path = Path(path)

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute('CREATE TABLE IF NOT EXISTS files (id TEXT PRIMARY KEY, record TEXT NOT NULL)')
        connection.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, time TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL)')
        return connection

    def upsert(self, records, event=None):
        connection = self._connect()
        try:
            with connection:
                # Reanalysis replaces metadata for this path without losing a second
                # byte-identical file that is already stored at a different path.
                paths = {record['current_path'] for record in records}
                identities = {record['id'] for record in records}
                obsolete = [(identity,) for identity, raw in connection.execute('SELECT id, record FROM files')
                            if identity not in identities and json.loads(raw)['current_path'] in paths]
                connection.executemany('DELETE FROM files WHERE id=?', obsolete)
                connection.executemany('INSERT INTO files VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET record=excluded.record',
                                       [(record['id'], json.dumps(record, ensure_ascii=False)) for record in records])
                if event:
                    connection.execute('INSERT INTO events(time, kind, detail) VALUES (?, ?, ?)',
                                       (datetime.now(timezone.utc).isoformat(), event['kind'], json.dumps(event['detail'], ensure_ascii=False)))
        finally:
            connection.close()

    def history(self, limit=100):
        if not self.path.exists():
            return []
        connection = self._connect()
        try:
            return [{'time': row[0], 'kind': row[1], 'detail': json.loads(row[2])}
                    for row in connection.execute('SELECT time, kind, detail FROM events ORDER BY id DESC LIMIT ?', (limit,))]
        finally:
            connection.close()

    def records(self):
        if not self.path.exists():
            return []
        connection = self._connect()
        try:
            return [json.loads(row[0]) for row in connection.execute('SELECT record FROM files ORDER BY id')]
        finally:
            connection.close()

    def search(self, query, records=None, limit=100):
        records = self.records() if records is None else records
        query_terms = terms(query)
        if not query.strip():
            return [{**record, 'score': 0.0} for record in records][:limit]
        if not query_terms:
            return []
        documents = [(record, terms(searchable(record))) for record in records]
        frequencies = Counter(term for _, tokens in documents for term in tokens)
        scored = []
        for record, tokens in documents:
            overlap = tokens & query_terms
            if not overlap:
                continue
            score = sum(math.log(1 + len(documents) / frequencies[token]) for token in overlap) / math.sqrt(max(1, len(tokens)))
            scored.append({**record, 'score': round(score, 4)})
        return sorted(scored, key=lambda item: (-item['score'], item['current_path']))[:limit]

    def similar(self, records, threshold=0.25, limit=100):
        """Rank shared summary/tag terms, excluding byte-identical pairs."""
        documents = [(r, terms(' '.join([r.get('summary', ''), *r.get('tags', [])]))) for r in records if not r.get('sensitive')]
        postings = defaultdict(list)
        for index, (_, tokens) in enumerate(documents):
            for token in tokens:
                postings[token].append(index)
        candidates = Counter()
        for indexes in postings.values():
            # Broad terms are poor evidence and can generate quadratic work.
            if len(indexes) > 100:
                continue
            for left in range(len(indexes)):
                for right in range(left + 1, len(indexes)):
                    candidates[(indexes[left], indexes[right])] += 1
        matches = []
        for (left, right), intersection in candidates.items():
            first, a = documents[left]
            second, b = documents[right]
            if first['sha256'] == second['sha256']:
                continue
            score = len(a & b) / len(a | b) if a | b else 0
            if score >= threshold:
                matches.append({'first': first['current_path'], 'second': second['current_path'], 'score': round(score, 3)})
        return sorted(matches, key=lambda pair: -pair['score'])[:limit]
