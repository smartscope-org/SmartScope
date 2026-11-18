from django.db import migrations


def backfill_collection_mode(apps, schema_editor):
    AutoloaderGrid = apps.get_model('API', 'AutoloaderGrid')
    for grid in AutoloaderGrid.objects.filter(collection_mode__isnull=True, params_id__isnull=False):
        grid.collection_mode = 'collection' if grid.params_id.holes_per_square <= 0 else 'screening'
        grid.save(update_fields=['collection_mode'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('API', '0035_alter_classifier_options_alter_finder_options_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_collection_mode, noop),
    ]
