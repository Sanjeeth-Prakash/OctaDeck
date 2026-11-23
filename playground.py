"""Validate file edits without executing their contents."""
import json
import re

MAX_EDIT_CHARS = 40_000


def check_filename(name):
    if name in (".", "..") or re.search(r'[\\/:*?"<>|\x00-\x1f]', name):
        raise ValueError("Choose a single imported filename.")


def validate_replacement(name, content):
    check_filename(name)
    if not content.strip() or "\0" in content:
        raise ValueError("Return nonempty text without binary characters.")
    if len(content) > MAX_EDIT_CHARS:
        raise ValueError("Replacement exceeds the file size limit.")
    try:
        if name.lower().endswith(".py"):
            compile(content, name, "exec", dont_inherit=True)
            return "Python syntax checked"
        if name.lower().endswith(".json"):
            json.loads(content)
            return "JSON syntax checked"
    except (SyntaxError, json.JSONDecodeError, RecursionError, OverflowError) as exc:
        raise ValueError("Invalid syntax for " + name) from exc
    return "Text and size checked"
