"""Validate AI and user-provided filenames and metadata before filesystem use."""
import math
import re
import unicodedata

RESERVED = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}


def name_component(value, limit=180, allow_hidden=False):
    if not isinstance(value, str):
        raise ValueError('폴더명과 파일명은 문자열이어야 합니다.')
    value = unicodedata.normalize('NFKC', value)
    if (not value or value in ('.', '..') or (value.startswith('.') and not allow_hidden)
            or value != value.strip() or value.endswith('.')
            or re.search(r'[\x00-\x1f\x7f<>:"/\\|?*]', value)
            or value.split('.')[0].upper() in RESERVED or len(value.encode('utf-8')) > limit):
        raise ValueError('허용되지 않는 폴더명 또는 파일명입니다.')
    return value


def folder_path(value):
    if isinstance(value, str):
        value = value.split('/')
    if not isinstance(value, list) or not 1 <= len(value) <= 3:
        raise ValueError('분류 폴더는 1~3단계로 지정하세요.')
    return '/'.join(name_component(part, 100) for part in value)


def normalized_result(result):
    if not isinstance(result, dict):
        raise ValueError('AI 분류 응답은 JSON 객체여야 합니다.')
    folder = folder_path(result.get('folder', result.get('category')))
    reason = result.get('reason')
    summary = result.get('summary', '')
    tags = result.get('tags', [])
    confidence = result.get('confidence', 0.0)
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('AI 분류 이유가 없습니다.')
    if (not isinstance(summary, str) or len(summary) > 2000
            or not isinstance(tags, list) or len(tags) > 12
            or any(not isinstance(tag, str) or not tag.strip() or len(tag) > 60 for tag in tags)
            or isinstance(confidence, bool) or not isinstance(confidence, (float, int))
            or not math.isfinite(confidence) or not 0 <= confidence <= 1):
        raise ValueError('AI 요약·태그·확신도 형식이 올바르지 않습니다.')
    return {'category': folder.split('/')[0], 'folder': folder, 'reason': reason[:300],
            'summary': summary[:1000], 'tags': list(dict.fromkeys(tag.strip() for tag in tags)),
            'confidence': confidence}
