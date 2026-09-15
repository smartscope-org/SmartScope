import os

def read_file(directory: str, name: str, start_line: int = None):
    try:
        with open(os.path.join(directory, name), 'r') as f:
            if start_line:
                file = ''.join(f.readlines()[start_line:])
            else:
                file = f.read()
        return file
    except FileNotFoundError as err:
        return ''


def read_file_line(directory: str, name: str, nline: int = 100):
    try:
        with open(os.path.join(directory, name), 'rb') as f:
            f.seek(0, os.SEEK_END)
            file_size = f.tell()
            block_size = 8192
            data = b''
            lines_found = 0
            pos = file_size

            while pos > 0 and lines_found <= nline:
                read_size = min(block_size, pos)
                pos -= read_size
                f.seek(pos)
                data = f.read(read_size) + data
                lines_found = data.count(b'\n')

            lines = data.splitlines()[-nline:]
            return [line.decode('utf-8', errors='replace') for line in lines]
    except FileNotFoundError as err:
        return ''