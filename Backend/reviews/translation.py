"""Translatable fields for customer reviews/comments.

Review titles and comments are user-generated in one language; the
translate_content management command can machine-fill the other languages,
and English/original always shows as the fallback.
"""
from modeltranslation.translator import register, TranslationOptions

from .models import Review


@register(Review)
class ReviewTranslationOptions(TranslationOptions):
    fields = ('title', 'comment')
