from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("cas_app", "0006_chiro_identity")]
    operations = [migrations.AddField(model_name="user", name="keycloak_roles_valid_after", field=models.BigIntegerField(default=0))]
