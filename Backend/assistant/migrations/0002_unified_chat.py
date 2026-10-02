from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('assistant', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # AssistantConversation: add title, status, needs_human, assigned_to
        migrations.AddField(
            model_name='assistantconversation',
            name='title',
            field=models.CharField(blank=True, default='', max_length=80),
        ),
        migrations.AddField(
            model_name='assistantconversation',
            name='status',
            field=models.CharField(
                choices=[('active', 'Active'), ('resolved', 'Resolved'), ('archived', 'Archived')],
                default='active',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='assistantconversation',
            name='needs_human',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='assistantconversation',
            name='assigned_to',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='assigned_conversations',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        # AssistantMessage: add admin role choice + sender_name
        migrations.AlterField(
            model_name='assistantmessage',
            name='role',
            field=models.CharField(
                choices=[
                    ('user', 'User'),
                    ('assistant', 'Assistant'),
                    ('tool', 'Tool'),
                    ('system', 'System'),
                    ('admin', 'Admin'),
                ],
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name='assistantmessage',
            name='sender_name',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
    ]
