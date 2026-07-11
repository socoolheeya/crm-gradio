import re


FORBIDDEN = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|COPY|CALL|DO|EXECUTE|BEGIN|COMMIT|ROLLBACK)\b", re.I)


def validate_read_only_sql(sql: str) -> str:
    cleaned = re.sub(r"^```(?:sql)?\s*|\s*```$", "", sql.strip(), flags=re.I)
    without_strings = re.sub(r"'(?:''|[^'])*'", "''", cleaned)
    if ";" in without_strings.rstrip(";") or FORBIDDEN.search(without_strings):
        raise ValueError("읽기 전용 단일 SQL만 허용됩니다")
    if not re.match(r"^(SELECT|WITH)\b", without_strings, re.I):
        raise ValueError("SELECT 쿼리만 허용됩니다")
    return cleaned.rstrip(";")
