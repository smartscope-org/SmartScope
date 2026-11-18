from django.db import migrations

# squares_num / holes_per_square: 0 used to mean "select all", now -1 means all and 0 means none.

def zero_to_minus_one(apps, schema_editor):
    GridCollectionParams = apps.get_model('API', 'GridCollectionParams')
    GridCollectionParams.objects.filter(squares_num=0).update(squares_num=-1)
    GridCollectionParams.objects.filter(holes_per_square=0).update(holes_per_square=-1)


def minus_one_to_zero(apps, schema_editor):
    GridCollectionParams = apps.get_model('API', 'GridCollectionParams')
    GridCollectionParams.objects.filter(squares_num__lt=0).update(squares_num=0)
    GridCollectionParams.objects.filter(holes_per_square__lt=0).update(holes_per_square=0)


class Migration(migrations.Migration):

    dependencies = [
        ('API', '0036_backfill_autoloadergrid_collection_mode'),
    ]

    operations = [
        migrations.RunPython(zero_to_minus_one, minus_one_to_zero),
    ]
