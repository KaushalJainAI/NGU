from decimal import Decimal, ROUND_HALF_UP

from rest_framework import serializers

from products.models import Product, ProductCombo, Category
from .models import UserEvent, UserGeo


class UserEventSerializer(serializers.Serializer):
    """
    Validates a single incoming behavioral event.

    The client sends ``*_id`` fields; existence is validated against the DB so
    a bad reference is dropped rather than raising an FK error at insert time.
    Unknown ids resolve to ``None`` (the event is still recorded for its type).
    """

    event_type = serializers.ChoiceField(choices=UserEvent.EVENT_TYPE_CHOICES)
    product_id = serializers.PrimaryKeyRelatedField(
        source='product', queryset=Product.objects.all(),
        required=False, allow_null=True,
    )
    combo_id = serializers.PrimaryKeyRelatedField(
        source='combo', queryset=ProductCombo.objects.all(),
        required=False, allow_null=True,
    )
    category_id = serializers.PrimaryKeyRelatedField(
        source='category', queryset=Category.objects.all(),
        required=False, allow_null=True,
    )
    query = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    metadata = serializers.DictField(required=False, default=dict)
    session_id = serializers.CharField(max_length=64, required=False, allow_blank=True, default='')

    def to_event(self, user) -> UserEvent:
        data = self.validated_data
        return UserEvent(
            user=user,
            event_type=data['event_type'],
            product=data.get('product'),
            combo=data.get('combo'),
            category=data.get('category'),
            query=data.get('query', '') or '',
            metadata=data.get('metadata', {}) or {},
            session_id=data.get('session_id', '') or '',
        )


def _round_coarse(value):
    """Round a coordinate to 3 decimals (~110 m) so we never store precise GPS."""
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)


class UserGeoSerializer(serializers.ModelSerializer):
    """
    Upsert a user's coarse location.

    The client may send precise lat/lng (e.g. straight from the browser
    geolocation API); we round them down here so only coarse coordinates ever
    reach the database. ``pincode`` is accepted in full and truncated to its
    region prefix.
    """

    # Accept precise input but never persist it verbatim.
    lat = serializers.FloatField(required=False, allow_null=True, write_only=True)
    lng = serializers.FloatField(required=False, allow_null=True, write_only=True)
    pincode = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = UserGeo
        fields = [
            'city', 'state', 'pincode_prefix',
            'lat_coarse', 'lng_coarse', 'updated_at',
            'lat', 'lng', 'pincode',
        ]
        read_only_fields = ['pincode_prefix', 'lat_coarse', 'lng_coarse', 'updated_at']

    def validate(self, attrs):
        lat = attrs.pop('lat', None)
        lng = attrs.pop('lng', None)
        pincode = attrs.pop('pincode', '') or ''
        if lat is not None:
            attrs['lat_coarse'] = _round_coarse(lat)
        if lng is not None:
            attrs['lng_coarse'] = _round_coarse(lng)
        if pincode:
            attrs['pincode_prefix'] = ''.join(c for c in pincode if c.isdigit())[:3]
        return attrs

    def upsert(self, user) -> UserGeo:
        obj, _ = UserGeo.objects.update_or_create(
            user=user, defaults=self.validated_data,
        )
        return obj
