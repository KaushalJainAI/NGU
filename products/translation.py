"""Registers which model fields django-modeltranslation manages.

Each registered field gets per-language columns (e.g. name_hi, description_gu).
Empty translations fall back to English (MODELTRANSLATION_FALLBACK_LANGUAGES),
so new products and untranslated fields always render. Product/Category names
are intentionally NOT auto-translated by any machine — admins enter curated
values; until then the English value shows.
"""
from modeltranslation.translator import register, TranslationOptions

from .models import Product, Category, ProductCombo


@register(Product)
class ProductTranslationOptions(TranslationOptions):
    fields = ('name', 'description', 'ingredients', 'origin_country', 'recipe')


@register(Category)
class CategoryTranslationOptions(TranslationOptions):
    fields = ('name', 'description')


@register(ProductCombo)
class ProductComboTranslationOptions(TranslationOptions):
    fields = ('name', 'title', 'description')
