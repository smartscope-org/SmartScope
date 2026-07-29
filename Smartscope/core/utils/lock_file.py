import os
import logging

logger = logging.getLogger(__name__)


class LockError(Exception):
    pass


def acquire_lock(lockdir_path: str, square_id: str):
    lock_file = os.path.join(lockdir_path, f'{square_id}.lock') 
    logger.info(f"Lock file for {square_id} under the path {lock_file}")
    try: 
        # O_CREAT | O_EXCL is atomic at the OS level:
        # if the file already exists, this raises FileExistsError instead of silently succeeding
        fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        logger.info(f"Lock file for {square_id} aquired")
        return lock_file
    except FileExistsError:
        raise LockError(f"Lock file for {os.path.basename(lock_file)} already exist.")
    

def release_lock(lock_path: str):
    try:
        os.remove(lock_path)
    except FileNotFoundError:
        pass