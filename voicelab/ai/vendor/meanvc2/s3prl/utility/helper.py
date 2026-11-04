"""Sustituto mínimo de s3prl.utility.helper: solo se usa ``show`` (mensajes)."""
import sys


def show(*args, **kwargs):
    kwargs.setdefault("file", sys.stderr)
    print(*args, **kwargs)
