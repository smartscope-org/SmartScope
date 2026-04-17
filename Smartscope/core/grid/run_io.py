import os
from Smartscope.lib.image.montage import Montage
from Smartscope.lib.file_manipulations.file_manipulations import split_path, file_busy, copy_file

def get_file(file, target_directory='raw', remove=True):
    path = split_path(file)
    file_busy(path.file, path.root)
    return copy_file(path.path, target_directory=target_directory, remove=remove)

def get_file_and_process(raw, name, directory='',target_directory='raw', force_reprocess=False):
    if force_reprocess or not os.path.isfile(raw):
        path = os.path.join(directory, raw)
        get_file(path, target_directory=target_directory, remove=True)
    montage = Montage(name)
    montage.load_or_process(force_process=force_reprocess)
    return montage