from django.db import migrations


class Migration(migrations.Migration):
    """Remove the order-scoped chat support system.

    The unified chat (assistant app) fully replaces ChatSession / ChatMessage.
    Drops both tables and their data. Depends on the assistant migration that
    removes the escalated_session FK pointing at ChatSession, so the referenced
    table can be dropped cleanly.
    """

    dependencies = [
        ('support', '0003_alter_chatmessage_attachment'),
        ('assistant', '0003_remove_escalated_session'),
    ]

    operations = [
        # ChatMessage first (it FKs ChatSession), then ChatSession.
        migrations.DeleteModel(name='ChatMessage'),
        migrations.DeleteModel(name='ChatSession'),
    ]
