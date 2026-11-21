import re


def cites(text: str, ref: str) -> bool:
    """True when `ref` is in `text` as a whole token.

    `logs/api.log:12` does not match `logs/api.log:120`, and `deploy:d-10`
    does not match `deploy:d-102`. A trailing `:` or sentence `.` is allowed,
    so the file ref `logs/api.log` matches the line ref `logs/api.log:120`.
    """
    pattern = rf"(?<![\w:/.-]){re.escape(ref)}(?![\w-]|\.\w)"
    return re.search(pattern, text) is not None
