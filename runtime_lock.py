"""Process lock released by the OS even after an interrupted shutdown."""
import os
from contextlib import contextmanager


@contextmanager
def single_instance(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as handle:
        if not path.stat().st_size:
            handle.write(b'0');handle.flush()
        handle.seek(0)
        if os.name=='nt':
            import msvcrt
            try:
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:
                raise BlockingIOError('Already running') from None
        else:
            import fcntl
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name=='nt':
                msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                fcntl.flock(handle,fcntl.LOCK_UN)
