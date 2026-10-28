"""Local per-source preferences. No API credentials or document content."""
import json
import os
from pathlib import Path
import uuid


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name('.hochi-' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def load_project(root):
    path = Path(root) / '.hochi-project.json'
    if path.is_symlink():
        raise ValueError('설정 파일에 링크를 사용할 수 없습니다.')
    data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    days = int(data.get('quiet_days', 7))
    if not 1 <= days <= 365:
        raise ValueError('후보 대기 기간은 1~365일로 지정하세요.')
    output = data.get('output', '')
    if not isinstance(output, str):
        raise ValueError('저장 폴더 설정이 올바르지 않습니다.')
    return {'output': output, 'quiet_days': days}


def save_project(engine, quiet_days):
    days = int(quiet_days)
    if not 1 <= days <= 365:
        raise ValueError('후보 대기 기간은 1~365일로 지정하세요.')
    with engine._locked():
        path = engine._safe(engine.root / '.hochi-project.json', engine.root)
        atomic_json(path, {'output': str(engine.output), 'quiet_days': days})
