import shutil
import logging
from Smartscope.core.models import AtlasModel, SquareModel
from pathlib import Path

logger = logging.getLogger(__name__)
mag_level_factory = {'atlas': AtlasModel, 'square': SquareModel}

EXPORT_DIRECTORY = Path('/mnt/data/training_data/')

class YoloFormat:
    bounding_boxes = []
    labels = []
    yolo_formatted = []

    def __init__(self, image:Path, shape_x, shape_y):
        self.image = Path(image)
        self.shape_x = shape_x
        self.shape_y = shape_y

    def append(self,bounding_box, label):
        self.bounding_boxes.append(bounding_box)
        self.labels.append(label)

    def convert(self):
        for bounding_box, label in zip(self.bounding_boxes, self.labels):
            x, y, x1, y1 = bounding_box
            x_center = ((x + x1) / 2) / self.shape_x
            y_center = ((y + y1) / 2) / self.shape_y
            width = (x1 - x) / self.shape_x
            height = (y1 - y) / self.shape_y

            self.yolo_formatted.append([label, x_center, y_center, width, height])

    def export(self, output_dir:Path):
        label_file = output_dir / self.image.with_suffix('.txt').name
        logger.info(f'Exporting to {label_file}')
        with open(output_dir / self.image.with_suffix('.txt').name, 'w') as file:
            for target in self.yolo_formatted:
                file.write(f"{target[0]} {target[1]} {target[2]} {target[3]} {target[4]}\n")
        logger.info(f'Copying image {self.image} to {output_dir}')
        shutil.copy2(self.image, output_dir)



EXPORT_FORMATS = {
    'yolo': YoloFormat
}


def get_bounding_box(x, y, radius):
    return [x - radius, y - radius, x + radius, y + radius]


def generate_training_data(instance, export_type: str = 'yolo'):
    query = list(instance.targets)


    training_data = EXPORT_FORMATS[export_type](image=instance.png, shape_x=instance.shape_x, shape_y=instance.shape_y)
    for target in query:
        finder = target.finders.first()
        x, y = finder.x, finder.y

        label = target.classifiers.filter(method_name=finder.method_name).values_list('label', flat=True)
        if len(label) == 0:
            label = target.classifiers.filter(method_name='Micrographs curation').values_list('label', flat=True)

        radius = target.radius

        coordinates = get_bounding_box(x, y, radius)

        training_data.append(bounding_box=coordinates, label=label[0] if len(label) > 0 else 0)
    
    training_data.convert()
    return training_data


# def export_training_data(data, instance, directory='/mnt/data/tmp/'):
#     image = f'{instance.pk}.mrc'
#     grid_type = instance.grid_id.meshMaterial.name
#     detection_type = instance.targets_prefix
#     shape_x = instance.shape_x
#     shape_y = instance.shape_y
#     output_dir = Path(directory, detection_type)
#     output_dir.mkdir(parents=True, exist_ok=True)
#     with open(output_dir / 'metadata.yaml', 'a+') as file:
#         file.write(yaml.dump([dict(image=image, shape_x=shape_x, shape_y=shape_y,
#                    grid_type=grid_type, targets=data)], default_flow_style=None))

#     shutil.copy(instance.mrc, output_dir / f'{instance.pk}.mrc')


def add_to_training_set(mag_level: str, id: str, dataset_name:str,export_type='yolo', output_directory=None, ):
    instance = mag_level_factory[mag_level].objects.get(pk=id)
    data = generate_training_data(instance=instance)
    if output_directory is None:
        output_directory = EXPORT_DIRECTORY / dataset_name
        output_directory.mkdir(parents=True, exist_ok=True)
    data.export(output_dir=output_directory)
