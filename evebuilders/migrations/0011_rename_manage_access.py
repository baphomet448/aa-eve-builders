"""Rename the permission manage_access to admin_access

The groups and the users that have it keep it: only the name of the permission
changes. The new permission manager_access is made by Django after the migration.
"""

# Django
from django.db import migrations

NAME = "Can manage everything in the plugin (admin)"
OLD_NAME = "Can manage build orders and plugin settings"


def rename(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")

    Permission.objects.filter(
        content_type__app_label="evebuilders", codename="manage_access"
    ).update(codename="admin_access", name=NAME)


def restore(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")

    Permission.objects.filter(
        content_type__app_label="evebuilders", codename="admin_access"
    ).update(codename="manage_access", name=OLD_NAME)


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("evebuilders", "0010_roles_permissions"),
    ]

    operations = [migrations.RunPython(rename, restore)]
