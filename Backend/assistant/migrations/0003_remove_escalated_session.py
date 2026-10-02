from django.db import migrations


class Migration(migrations.Migration):
    """Drop the deprecated escalated_session FK to support.ChatSession.

    Human-admin participation now lives directly on AssistantMessage (role
    'admin'), so the link to the retired support.ChatSession is removed. This
    must run before support drops the ChatSession table.
    """

    dependencies = [
        ('assistant', '0002_unified_chat'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='assistantconversation',
            name='escalated_session',
        ),
    ]
