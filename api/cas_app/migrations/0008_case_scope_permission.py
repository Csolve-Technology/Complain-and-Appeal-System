from django.db import migrations

def grant_existing_staff_scope(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    content_type, _ = ContentType.objects.get_or_create(app_label="cas_app", model="case")
    permission, _ = Permission.objects.get_or_create(content_type=content_type, codename="view_all_cases", defaults={"name":"Can view cases across applicants"})
    for group in Group.objects.filter(name__in=["Admin", "Mayor Office", "Director", "Focal Person"]):
        group.permissions.add(permission)

class Migration(migrations.Migration):
    dependencies = [("cas_app", "0007_role_token_freshness")]
    operations = [
        migrations.AlterModelOptions(name="case", options={"ordering":["-created_at"],"permissions":[("view_all_cases", "Can view cases across applicants")]}),
        migrations.RunPython(grant_existing_staff_scope, migrations.RunPython.noop),
    ]
