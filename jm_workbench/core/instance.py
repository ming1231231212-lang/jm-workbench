"""One execution service owns each data directory, even across different ports."""
import os


class InstanceLock:
    def __init__(self, path):
        self.file = open(path, 'a+b')
        self.file.seek(0)
        self.file.write(b'0')
        self.file.flush()
        self.file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError('此数据目录已有JM执行服务，不能启动第二个执行器')

    def close(self):
        self.file.close()
