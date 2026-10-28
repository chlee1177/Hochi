"""Observe local changes; suggest versions without claiming to know actual usage."""
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid

from folder_organizer import check_cancel, digest, is_link, snapshot
from project import atomic_json


def suggested_name(path):
    stem = Path(path).stem.casefold()
    stem = re.sub(r'(?:최)+종|최신|수정본?|완성본?|final|draft|ver(?:sion)?[ _.-]*\d+|[ _.-]v\d+', '', stem)
    stem = re.sub(r'[ _()\-]+', '', stem)
    return stem or Path(path).stem


class VersionMonitor:
    def __init__(self, engine, quiet_days=7, clock=time.time):
        self.engine = engine
        self.quiet_days = int(quiet_days)
        if not 1 <= self.quiet_days <= 365:
            raise ValueError('후보 대기 기간은 1~365일로 지정하세요.')
        self.clock = clock
        self.path = engine._safe(engine.output / '.hochi-versions.json', engine.output)

    def load(self):
        self.engine._validate_output()
        if not self.path.exists():
            return {'version': 1, 'files': {}, 'groups': {}}
        state = json.loads(self.path.read_text(encoding='utf-8'))
        if state.get('version') != 1 or not isinstance(state.get('files'), dict) or not isinstance(state.get('groups'), dict):
            raise ValueError('버전 기록 형식이 올바르지 않습니다.')
        return state

    def paths(self):
        engine = self.engine
        roots = [engine.root]
        if not engine.output.is_relative_to(engine.root) and engine.output.exists():
            roots.append(engine.output)
        def failed(error):
            raise error
        for root in roots:
            if not root.is_dir():
                raise ValueError('감시 폴더에 접근할 수 없습니다. 디스크 연결을 확인하세요.')
            for directory, dirs, names in os.walk(root, followlinks=False, onerror=failed):
                base = Path(directory)
                dirs[:] = [name for name in dirs if not is_link(base / name) and not name.startswith('.hochi')]
                for name in names:
                    path = base / name
                    if (name.startswith(('.hochi', '.journal-', '~$')) or path.suffix.lower() in ('.tmp', '.part', '.crdownload')
                            or is_link(path) or not path.is_file()):
                        continue
                    yield path

    def refresh(self, cancel=None):
        now = self.clock()
        with self.engine._locked():
            state = self.load()
            old = state['files']
            scanned, unstable = {}, set()
            for path in self.paths():
                check_cancel(cancel)
                key = str(path)
                try:
                    before = snapshot(path)
                    checksum = hashlib.sha256()
                    with path.open('rb') as stream:
                        while chunk := stream.read(1024 * 1024):
                            check_cancel(cancel)
                            checksum.update(chunk)
                    if snapshot(path) != before:
                        unstable.add(key)
                        continue
                    scanned[key] = (before, checksum.hexdigest())
                except FileNotFoundError:
                    unstable.add(key)
            # Preserve identity on an unambiguous rename/move, including our own moves.
            missing = defaultdict(list)
            for path, record in old.items():
                if path not in scanned and path not in unstable and record.get('present'):
                    missing[record['sha256']].append(path)
            new_hashes = defaultdict(list)
            for path, (_, checksum) in scanned.items():
                if path not in old:
                    new_hashes[checksum].append(path)
            for record in old.values():
                if record.get('present') and record['path'] not in scanned and record['path'] not in unstable:
                    state['groups'].setdefault(record['group'], {})['activity_at'] = now
                record['present'] = False
            for path in unstable:
                if path in old:
                    old[path]['present'] = True
            for path, (stat, checksum) in scanned.items():
                record = old.get(path)
                if record is None and len(missing[checksum]) == len(new_hashes[checksum]) == 1:
                    record = old.pop(missing[checksum][0])
                if record is None:
                    identity = uuid.uuid4().hex
                    record = {'id': identity, 'group': identity, 'first_seen': now, 'changed_at': now}
                elif record.get('sha256') != checksum:
                    record['changed_at'] = now
                if record.get('changed_at') == now:
                    state['groups'].setdefault(record['group'], {})['activity_at'] = now
                record.update(path=path, sha256=checksum, snapshot=stat, present=True,
                              suggestion=suggested_name(path))
                old[path] = record
            check_cancel(cancel)
            atomic_json(self.path, state)
            return self.rows(state)

    def rows(self, state=None):
        state = self.load() if state is None else state
        groups = defaultdict(list)
        for record in state['files'].values():
            if record.get('present'):
                groups[record['group']].append(record)
        rows = []
        for group, members in groups.items():
            settings = state['groups'].get(group, {})
            final = settings.get('final')
            latest = max(members, key=lambda r: (r['changed_at'], r['snapshot'][1], r['path']))
            activity = max(settings.get('activity_at', 0), max(r['changed_at'] for r in members))
            quiet = self.clock() - activity >= self.quiet_days * 86400
            confirmed = next((r for r in members if final and r['id'] == final['id'] and r['sha256'] == final['sha256']), None)
            warning = bool(final and (not confirmed or activity > final['at']))
            for record in members:
                status = ('확정 최종본' if record is confirmed else '이전 버전' if confirmed else
                          '최종본 후보' if record is latest and quiet else
                          '최근 수정본' if record is latest else '다른 버전')
                rows.append({**record, 'version_state': status, 'group_name': settings.get('name', ''),
                             'warning': '최종본 확정 후 변경 또는 삭제 · 재확인 필요' if warning else '',
                             'group_confirmed': bool(settings.get('name'))})
        by_path = {r['path']: r for r in rows}
        suggestions = defaultdict(set)
        names = defaultdict(list)
        warned = set()
        for row in rows:
            names[row['suggestion']].append(row)
        for members in names.values():
            newest = {}
            for row in members:
                newest[row['group']] = max(newest.get(row['group'], 0), row['changed_at'])
            latest_groups = sorted(newest.items(), key=lambda pair: -pair[1])[:2]
            for row in members:
                final = state['groups'].get(row['group'], {}).get('final')
                if final and any(group != row['group'] and changed > final['at'] for group, changed in latest_groups):
                    warned.add(row['group'])
        for pair in self.engine.similar():
            first = str(self.engine.resolve_record(pair['first']))
            second = str(self.engine.resolve_record(pair['second']))
            if first in by_path and second in by_path and by_path[first]['group'] != by_path[second]['group']:
                suggestions[first].add(second)
                suggestions[second].add(first)
                by_path[first].setdefault('related', '요약·태그 유사 후보: ' + Path(second).name)
                by_path[second].setdefault('related', '요약·태그 유사 후보: ' + Path(first).name)
        for row in rows:
            final = state['groups'].get(row['group'], {}).get('final')
            if final and any(by_path[path]['changed_at'] > final['at'] for path in suggestions[row['path']]):
                warned.add(row['group'])
        for row in rows:
            if row['group'] in warned and not row['warning']:
                row['warning'] = '새 버전 후보 확인 필요 · 묶음 제안 검토'
        return sorted(rows, key=lambda r: (r['group_name'] or r['suggestion'], r['path']))

    def group(self, paths, name):
        name = name.strip()
        if not name or len(name) > 100:
            raise ValueError('문서 묶음 이름은 1~100자로 입력하세요.')
        if len(set(paths)) < 2:
            raise ValueError('같은 문서의 파일을 두 개 이상 선택하세요.')
        with self.engine._locked():
            state = self.load()
            records = [self._current(state, path) for path in paths]
            identity = uuid.uuid4().hex
            for record in records:
                record['group'] = identity
            state['groups'][identity] = {'name': name, 'activity_at': self.clock()}
            atomic_json(self.path, state)
            return self.rows(state)

    def _current(self, state, path):
        record = state['files'].get(path)
        safe = self.engine.resolve_record(path)
        if not record or not record.get('present') or not safe.is_file() or digest(safe) != record['sha256']:
            raise ValueError('파일이 변경되었거나 없습니다. 새로고침 후 다시 확인하세요.')
        return record

    def confirm(self, path):
        with self.engine._locked():
            state = self.load()
            record = self._current(state, path)
            group = state['groups'].setdefault(record['group'], {})
            group['final'] = {'id': record['id'], 'sha256': record['sha256'], 'at': self.clock()}
            atomic_json(self.path, state)
            return self.rows(state)

    def release(self, paths, ungroup=False):
        with self.engine._locked():
            state = self.load()
            for path in paths:
                record = self._current(state, path)
                group = state['groups'].get(record['group'], {})
                group.pop('final', None)
                if ungroup:
                    record['group'] = uuid.uuid4().hex
            atomic_json(self.path, state)
            return self.rows(state)

    def search_records(self, records, include_previous=False):
        state = self.load()
        # Search never trusts stale confirmations, even while monitoring is paused.
        for record in state['files'].values():
            if not record.get('present'):
                continue
            path = self.engine.resolve_record(record['path'])
            if not path.is_file():
                record['present'] = False
                state['groups'].setdefault(record['group'], {})['activity_at'] = self.clock()
            else:
                checksum = digest(path)
                if checksum != record['sha256']:
                    record['sha256'] = checksum
                    record['changed_at'] = self.clock()
        versions = {r['path']: r for r in self.rows(state)}
        result, indexed = [], set()
        for record in records:
            path = str(self.engine.resolve_record(record['current_path']))
            version = versions.get(path, {})
            if version and version['sha256'] != record['sha256']:
                continue
            indexed.add(path)
            if version.get('version_state') == '이전 버전' and not include_previous and not version.get('warning'):
                continue
            result.append({**record, 'version_state': version.get('version_state', ''),
                           'tags': [*record.get('tags', []), *filter(None, [version.get('version_state'), version.get('warning')])]})
        for path, version in versions.items():
            if path in indexed or not version['sha256']:
                continue
            if version['version_state'] == '이전 버전' and not include_previous and not version['warning']:
                continue
            result.append({'current_path': self.engine.record_path(Path(path)), 'folder': '',
                           'tags': [version['version_state'], *([version['warning']] if version['warning'] else [])],
                           'version_state': version['version_state'], 'summary': '', 'reason': '감시로 발견 · AI 내용 분석 전'})
        return result
