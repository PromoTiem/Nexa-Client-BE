"""PocketBase string literals shared by infrastructure and application code."""

import re

_UNSAFE = re.compile(r'["\\]')


def sanitize_filter_value(value: str) -> str:
    return _UNSAFE.sub(lambda match: "\\" + match.group(0), value)
