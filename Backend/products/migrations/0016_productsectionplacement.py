"""Introduce ProductSectionPlacement (ordered Product<->ProductSection).

This converts the auto-created M2M ``products_product_sections`` join table into
an explicit through model WITHOUT losing existing placements. We reuse the same
table (same name, same columns product_id/productsection_id) and only ADD a
``position`` column to it, then seed positions from current row order.

SeparateDatabaseAndState is used because, project-state-wise, we create a new
model + repoint the M2M, but database-wise the table already exists, so the
only real schema change is the new column (added via RunSQL so it does not
depend on the model being present in the database-operations state).
"""
from django.db import migrations, models
import django.db.models.deletion


def seed_positions(apps, schema_editor):
    """Assign an initial position per section, following current row order."""
    Placement = apps.get_model('products', 'ProductSectionPlacement')
    by_section = {}
    for row in Placement.objects.all().order_by('section_id', 'id'):
        idx = by_section.get(row.section_id, 0)
        if row.position != idx:
            row.position = idx
            row.save(update_fields=['position'])
        by_section[row.section_id] = idx + 1


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0015_alter_productsection_max_products'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            # --- project state only (no SQL): model exists + M2M now uses it ---
            state_operations=[
                migrations.CreateModel(
                    name='ProductSectionPlacement',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('position', models.PositiveIntegerField(default=0, help_text='Order of this product within the section (lower shows first)')),
                        ('product', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='products.product')),
                        ('section', models.ForeignKey(db_column='productsection_id', on_delete=django.db.models.deletion.CASCADE, to='products.productsection')),
                    ],
                    options={
                        'db_table': 'products_product_sections',
                        'ordering': ['position'],
                        'unique_together': {('product', 'section')},
                    },
                ),
                migrations.AlterField(
                    model_name='product',
                    name='sections',
                    field=models.ManyToManyField(blank=True, help_text='Homepage sections where this product appears', related_name='products', through='products.ProductSectionPlacement', to='products.productsection'),
                ),
            ],
            # --- database only: the table already exists; just add the column ---
            database_operations=[
                migrations.RunSQL(
                    sql='ALTER TABLE products_product_sections ADD COLUMN position integer NOT NULL DEFAULT 0;',
                    reverse_sql='ALTER TABLE products_product_sections DROP COLUMN position;',
                ),
            ],
        ),
        migrations.RunPython(seed_positions, migrations.RunPython.noop),
    ]
