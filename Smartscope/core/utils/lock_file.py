import os


class LockError(Exception):
    pass


def acquire_lock(lock_path: str):
    lock_file = os.path.join(lock_path, ".lock") 
    try: 
        # O_CREAT | O_EXCL is atomic at the OS level:
        # if the file already exists, this raises FileExistsError instead of silently succeeding
        fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return lock_path
    except FileExistsError:
        raise LockError(f"Lock file for {os.path.basename(lock_path)} already exist.")
    

def release_lock(lock_path: str):
    try:
        os.remove(lock_path)
    except FileNotFoundError:
        pass