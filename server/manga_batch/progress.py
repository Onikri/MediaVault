"""Request-local, credential-free progress; safe with concurrent model workers."""
from contextlib import contextmanager
from contextvars import ContextVar

_listener = ContextVar('manga_progress_listener', default=None)

@contextmanager
def observing(listener):
    token = _listener.set(listener)
    try: yield
    finally: _listener.reset(token)

def report(phase, message, **details):
    listener = _listener.get()
    if listener is not None: listener({'phase': phase, 'message': message, **details})
