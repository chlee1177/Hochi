"""Local screening only. Never sends filenames or contents to a service."""
import re
import unicodedata

NAME_TERMS = ('주민등록', '급여', '계약서', '의료', '진료', '처방', '여권', '인증서',
              '비밀번호', '회사기밀', '대외비', '사내기밀', 'confidential', 'payroll',
              'salary', 'passport', 'medical', 'contract', 'credential', 'password',
              'secret', 'id_rsa', 'id_ed25519')
SECRET_EXTENSIONS = {'.pem', '.key', '.p12', '.pfx', '.keystore'}
PATTERNS = (
    ('주민등록번호 형태', re.compile(r'(?<!\d)\d{6}[\s-]?[1-8]\d{6}(?!\d)')),
    ('개인키 블록', re.compile(r'-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----')),
    ('API 키 형태', re.compile(r'\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{16,}|AKIA[A-Z0-9]{16})\b')),
    ('인증정보 할당', re.compile(r'(?i)(?:api[_-]?key|access[_-]?token|password|비밀번호)\s*[:=]\s*["\x27]?\S{4,}')),
    ('이메일 주소', re.compile(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}')),
    ('전화번호 형태', re.compile(r'(?<!\d)01[016789][ -]?\d{3,4}[ -]?\d{4}(?!\d)')),
)


def screen_name(relative, extra_terms=()):
    value = unicodedata.normalize('NFKC', str(relative)).casefold()
    reasons = []
    if any(term.casefold() in value for term in (*NAME_TERMS, *extra_terms) if term.strip()):
        reasons.append('민감 파일명 또는 경로 키워드')
    name = value.replace('\\', '/').rsplit('/', 1)[-1]
    if name == '.env' or name.startswith('.env.') or any(name.endswith(ext) for ext in SECRET_EXTENSIONS):
        reasons.append('인증정보 파일 형식')
    reasons.extend(label for label, pattern in PATTERNS if pattern.search(value))
    return list(dict.fromkeys(reasons))


def screen_content(parts, scope):
    reasons = []
    for part in parts:
        if part.get('type') == 'input_image':
            reasons.append('이미지의 민감정보를 로컬에서 검사할 수 없음')
        if part.get('type') == 'input_text':
            value = unicodedata.normalize('NFKC', part.get('text', ''))
            reasons.extend(label for label, pattern in PATTERNS if pattern.search(value))
            if any(word in value.casefold() for word in ('대외비', '기밀', 'confidential', '주민등록등본', '급여명세', '진료기록')):
                reasons.append('민감 문서 내용 키워드')
    if any(word in scope for word in ('암호화', '스캔 PDF', '추출 불가', '인코딩 미지원')):
        reasons.append('내용을 로컬에서 검사할 수 없음')
    return list(dict.fromkeys(reasons))
