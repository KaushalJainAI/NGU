# shop/management/commands/populate_search_kb.py
from django.core.management.base import BaseCommand
from products.recommendations import SpiceSearchEngine
from products.models import Product, ProductCombo

class Command(BaseCommand):
    help = (
        'Populate LLM search KB for products and combos. '
        'Run with --force after any direct-SQL catalog change '
        '(raw SQL bypasses the signals that refresh the KB).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force regenerate even fresh entries',
        )

    def handle(self, *args, **options):
        engine = SpiceSearchEngine()
        force = options.get('force', False)

        products = Product.objects.filter(is_active=True)
        combos = ProductCombo.objects.filter(is_active=True)

        self.stdout.write(f'Processing {products.count()} products...')
        for i, product in enumerate(products, 1):
            engine.ensure_search_kb(product, force=force)
            count = len(product.search_kb.get_synonyms_list()) if hasattr(product, 'search_kb') else 0
            self.stdout.write(f'  [{i}/{products.count()}] ✓ {product.name} ({count} synonyms)')

        self.stdout.write(f'\nProcessing {combos.count()} combos...')
        for i, combo in enumerate(combos, 1):
            engine.ensure_search_kb(combo, force=force)
            count = len(combo.search_kb.get_synonyms_list()) if hasattr(combo, 'search_kb') else 0
            self.stdout.write(f'  [{i}/{combos.count()}] ✓ {combo.name} ({count} synonyms)')

        self.stdout.write(self.style.SUCCESS('\n✅ Done! Search KB is ready (search cache invalidated).'))
