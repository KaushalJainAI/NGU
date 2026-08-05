from rest_framework import serializers
from .models import Review
from spices_backend.limits import MAX_REVIEW_COMMENT

class ReviewSerializer(serializers.ModelSerializer):
    # Public display name. NOT `user.username`: for Google sign-ins the username
    # is derived from the email's local part, so reviews were publishing the
    # customer's email handle. Prefer whatever they actually call themselves.
    user_name = serializers.SerializerMethodField(read_only=True)
    item_name = serializers.CharField(read_only=True)
    # Bound the free-text comment (model field is an unbounded TextField) so a
    # malicious user can't submit a multi-megabyte review.
    comment = serializers.CharField(max_length=MAX_REVIEW_COMMENT, allow_blank=True, required=False)
    # The storefront form marks the title optional; accept it as such rather
    # than 400-ing on a field the customer was invited to skip.
    title = serializers.CharField(max_length=200, allow_blank=True, required=False, default='')

    class Meta:
        model = Review
        fields = ['id', 'item_type', 'product', 'combo', 'user', 'user_name', 'item_name',
                  'rating', 'title', 'comment', 'is_verified_purchase', 'is_hidden',
                  'is_featured', 'created_at']
        # is_hidden is moderation state and is_featured is homepage placement:
        # both are changed only via their staff-only actions, never through a
        # normal review create/update.
        read_only_fields = ['user', 'is_verified_purchase', 'item_name', 'is_hidden',
                            'is_featured']

    def get_user_name(self, obj):
        """Public display name for the review author.

        Never falls back to `username`. For a Google sign-in the username is
        derived from the email's local part (users/views.py), so returning it
        publishes a piece of the customer's email address on a page anyone can
        read — including the unauthenticated home-page testimonials strip. An
        email/password customer who never filled in a name has no display name
        to publish at all, so the review is attributed generically rather than
        by leaking the one identifier we do hold.
        """
        user = obj.user
        if not user:
            return ''
        # `name` is the profile's own display field; then the Django name fields.
        for candidate in (
            getattr(user, 'name', '') or '',
            (f"{user.first_name} {user.last_name}").strip(),
            user.first_name or '',
        ):
            if candidate.strip():
                return candidate.strip()
        return 'Customer'

    def validate(self, data):
        # Be partial-update aware: on a PATCH that only edits rating/comment the
        # item fields are absent, so fall back to the existing instance instead
        # of wrongly demanding `product`/`combo` again (which blocked legit edits).
        instance = getattr(self, 'instance', None)
        item_type = data.get('item_type') or (instance.item_type if instance else 'product')
        product = data.get('product') if 'product' in data else (instance.product if instance else None)
        combo = data.get('combo') if 'combo' in data else (instance.combo if instance else None)

        if item_type == 'product' and not product:
            raise serializers.ValidationError("Product is required for product reviews")
        if item_type == 'combo' and not combo:
            raise serializers.ValidationError("Combo is required for combo reviews")

        return data
