"""
Cart Views - Shopping Cart API

Architecture:
- CartViewSet: Main cart operations (list, add, update, remove, sync)
- ValidateCouponAPIView: Coupon validation for checkout
- CartPaymentQRView: UPI QR code generation for payment
- FavoritesViewSet: Wishlist/favorites management

Key Design Decisions:
1. Cart items support both Products AND Combos via item_type field
2. Stock validation happens on add/update to prevent overselling
3. Sync endpoint allows merging localStorage cart with backend on login
4. All operations use atomic transactions to prevent race conditions
5. Quantity validation: must be positive integer (no negative, no floats)
6. ALL responses are built via DRF serializers — no manual dict construction

Item Identification:
- Products: identified by product_id + item_type='product'
- Combos: identified by product_id + item_type='combo'
- Remove accepts composite keys: "product-123" or "combo-456"
"""

import logging
from decimal import Decimal

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from django.db import transaction

from .models import Cart, CartItem, Favorite
from .serializers import (
    CartResponseSerializer,
    FavoriteItemSerializer,
    ValidateCouponSerializer,
)
from admin_panel.utils import generate_upi_qr_code
from admin_panel.models import Coupon, ReceivableAccount
from products.models import Product, ProductCombo, ProductVariant
from spices_backend.limits import MAX_ITEM_QUANTITY, MAX_CART_ITEMS, MAX_SYNC_ITEMS
from spices_backend.abuse import flag_suspicious

logger = logging.getLogger(__name__)


def _resolve_variant(product, variant_id, *, lock=False):
    """Return the ProductVariant for a product line.

    If variant_id is given it must be an active variant of `product`; otherwise
    fall back to the product's default (or first active) variant so older
    clients that only send product_id keep working. Returns None if the product
    has no variants at all (legacy data) — callers then fall back to the
    product's own stock/price.
    """
    qs = ProductVariant.objects.filter(product=product, is_active=True)
    if lock:
        qs = qs.select_for_update()
    if variant_id:
        try:
            return qs.get(id=int(variant_id))
        except (ProductVariant.DoesNotExist, ValueError, TypeError):
            return None
    return qs.order_by('-is_default', 'display_order', 'weight').first()


class CartViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    # Rate-limit cart mutations so rapid-fire abuse can't hammer the DB; reads
    # are unaffected.
    _WRITE_ACTIONS = {'add_item', 'update_item', 'remove_item', 'clear', 'sync'}

    def get_throttles(self):
        if getattr(self, 'action', None) in self._WRITE_ACTIONS:
            from spices_backend.throttles import CartWriteThrottle
            return [CartWriteThrottle()]
        return super().get_throttles()

    # ------------------------------------------------------------------
    # Helper: build a serialized cart response (used by every endpoint)
    # ------------------------------------------------------------------
    def _cart_response(self, request):
        """Return a fully serialized cart response."""
        cart, _ = Cart.objects.get_or_create(user=request.user)
        serializer = CartResponseSerializer(
            {'cart': cart},
            context={'request': request},
        )
        return Response(serializer.data)

    # ------------------------------------------------------------------
    # LIST
    # ------------------------------------------------------------------
    def list(self, request):
        return self._cart_response(request)

    # ------------------------------------------------------------------
    # ADD ITEM
    # ------------------------------------------------------------------
    @action(detail=False, methods=['post'])
    def add_item(self, request):
        product_id = request.data.get('product_id') or request.data.get('id')
        item_type = request.data.get('item_type', 'product')
        variant_id = request.data.get('variant_id')

        # Validate item_type
        if item_type not in ('product', 'combo'):
            return Response({
                'success': False,
                'error': "item_type must be 'product' or 'combo'"
            }, status=status.HTTP_400_BAD_REQUEST)

        # Validate quantity is a natural number (positive integer >= 1)
        raw_quantity = request.data.get('quantity', 1)
        try:
            quantity = int(raw_quantity)
            if quantity < 1:
                return Response({
                    'success': False,
                    'error': 'Quantity must be a positive integer (1 or greater)'
                }, status=status.HTTP_400_BAD_REQUEST)
        except (ValueError, TypeError):
            return Response({
                'success': False,
                'error': 'Quantity must be a valid integer'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Upper bound: an extreme quantity can overflow the order money columns
        # at checkout and is a classic abuse vector — reject and flag it.
        if quantity > MAX_ITEM_QUANTITY:
            flag_suspicious(request, reason='cart.add_item.quantity', value=quantity)
            return Response({
                'success': False,
                'error': f'Quantity cannot exceed {MAX_ITEM_QUANTITY} per item.'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Validate product_id is provided and is a valid integer
        if not product_id:
            return Response({'success': False, 'error': 'Product id required'},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            product_id = int(product_id)
        except (ValueError, TypeError):
            return Response({
                'success': False,
                'error': 'Product id must be a valid integer'
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                cart, _ = Cart.objects.get_or_create(user=request.user)

                if item_type == 'combo':
                    item = ProductCombo.objects.select_for_update().get(id=product_id, is_active=True)
                    stock = getattr(item, 'stock', 999)

                    # Check for existing cart item with lock
                    cart_item = CartItem.objects.select_for_update().filter(
                        cart=cart, combo=item, item_type='combo'
                    ).first()

                    if cart_item:
                        new_quantity = cart_item.quantity + quantity
                        if new_quantity > stock:
                            return Response({'success': False, 'error': f'Only {stock} units available'},
                                            status=status.HTTP_400_BAD_REQUEST)
                        cart_item.quantity = new_quantity
                        cart_item.save()
                    else:
                        if quantity > stock:
                            return Response({'success': False, 'error': f'Only {stock} units available'},
                                            status=status.HTTP_400_BAD_REQUEST)
                        if cart.items.count() >= MAX_CART_ITEMS:
                            return Response({'success': False,
                                             'error': f'Your cart can hold at most {MAX_CART_ITEMS} different items.'},
                                            status=status.HTTP_400_BAD_REQUEST)
                        CartItem.objects.create(cart=cart, combo=item, item_type='combo', quantity=quantity)
                else:
                    item = Product.objects.select_for_update().get(id=product_id, is_active=True)
                    variant = _resolve_variant(item, variant_id, lock=True)
                    if variant_id and variant is None:
                        return Response({'success': False, 'error': 'Selected size is unavailable'},
                                        status=status.HTTP_400_BAD_REQUEST)
                    stock = variant.stock if variant else item.stock

                    # A cart line is identified by its variant (or the product
                    # itself for legacy variant-less data).
                    if variant:
                        cart_item = CartItem.objects.select_for_update().filter(
                            cart=cart, variant=variant, item_type='product'
                        ).first()
                    else:
                        cart_item = CartItem.objects.select_for_update().filter(
                            cart=cart, product=item, variant__isnull=True, item_type='product'
                        ).first()

                    if cart_item:
                        new_quantity = cart_item.quantity + quantity
                        if new_quantity > stock:
                            return Response({'success': False, 'error': f'Only {stock} units available'},
                                            status=status.HTTP_400_BAD_REQUEST)
                        cart_item.quantity = new_quantity
                        cart_item.save()
                    else:
                        if quantity > stock:
                            return Response({'success': False, 'error': f'Only {stock} units available'},
                                            status=status.HTTP_400_BAD_REQUEST)
                        if cart.items.count() >= MAX_CART_ITEMS:
                            return Response({'success': False,
                                             'error': f'Your cart can hold at most {MAX_CART_ITEMS} different items.'},
                                            status=status.HTTP_400_BAD_REQUEST)
                        CartItem.objects.create(cart=cart, product=item, variant=variant,
                                                item_type='product', quantity=quantity)

        except (Product.DoesNotExist, ProductCombo.DoesNotExist):
            return Response({'success': False, 'error': 'Item not found'},
                            status=status.HTTP_404_NOT_FOUND)
        except Exception:
            logger.exception("Failed to add item to cart")
            return Response({'success': False,
                             'error': 'Something went wrong while adding the item. Please try again.'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return self._cart_response(request)

    # ------------------------------------------------------------------
    # UPDATE ITEM
    # ------------------------------------------------------------------
    @action(detail=False, methods=['post'])
    def update_item(self, request):
        product_id = request.data.get('product_id') or request.data.get('id')
        item_type = request.data.get('item_type', 'product')
        variant_id = request.data.get('variant_id')

        # Validate item_type
        if item_type not in ('product', 'combo'):
            return Response({
                'success': False,
                'error': "item_type must be 'product' or 'combo'"
            }, status=status.HTTP_400_BAD_REQUEST)

        # Validate quantity is a valid integer
        raw_quantity = request.data.get('quantity', 1)
        try:
            quantity = int(raw_quantity)
            # For update, allow 0 or positive (0 means remove)
            if quantity < 0:
                return Response({
                    'success': False,
                    'error': 'Quantity cannot be negative'
                }, status=status.HTTP_400_BAD_REQUEST)
        except (ValueError, TypeError):
            return Response({
                'success': False,
                'error': 'Quantity must be a valid integer'
            }, status=status.HTTP_400_BAD_REQUEST)

        if quantity > MAX_ITEM_QUANTITY:
            flag_suspicious(request, reason='cart.update_item.quantity', value=quantity)
            return Response({
                'success': False,
                'error': f'Quantity cannot exceed {MAX_ITEM_QUANTITY} per item.'
            }, status=status.HTTP_400_BAD_REQUEST)

        if not product_id:
            return Response({'success': False, 'error': 'Product id required'},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            product_id = int(product_id)
        except (ValueError, TypeError):
            return Response({
                'success': False,
                'error': 'Product id must be a valid integer'
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                cart = get_object_or_404(Cart, user=request.user)

                if item_type == 'combo':
                    item = ProductCombo.objects.select_for_update().get(id=product_id, is_active=True)
                    cart_item = CartItem.objects.select_for_update().get(cart=cart, combo=item, item_type='combo')
                    stock = getattr(item, 'stock', 999)
                else:
                    item = Product.objects.select_for_update().get(id=product_id, is_active=True)
                    variant = _resolve_variant(item, variant_id, lock=True)
                    cart_item = None
                    if variant:
                        cart_item = CartItem.objects.select_for_update().filter(
                            cart=cart, variant=variant, item_type='product').first()
                        stock = variant.stock
                    else:
                        stock = item.stock
                    if cart_item is None and not variant_id:
                        # Legacy line: added before this product had any size, so
                        # it carries variant=NULL and the resolved default above
                        # matches nothing. Every product now gets a default size
                        # (products.signals), which would otherwise make every
                        # such pre-existing cart row permanently unmodifiable —
                        # "Cart item not found" on any quantity change. Only fall
                        # back when the caller did NOT name a specific size, so
                        # an explicit variant_id can never hit the wrong line.
                        cart_item = CartItem.objects.select_for_update().filter(
                            cart=cart, product=item, variant__isnull=True,
                            item_type='product').first()
                        if cart_item is not None and variant is None:
                            stock = item.stock
                    if cart_item is None:
                        raise CartItem.DoesNotExist()

                if quantity <= 0:
                    cart_item.delete()
                else:
                    if stock < quantity:
                        return Response({'success': False, 'error': f'Only {stock} units available'},
                                        status=status.HTTP_400_BAD_REQUEST)
                    cart_item.quantity = quantity
                    cart_item.save()

        except (CartItem.DoesNotExist, Product.DoesNotExist, ProductCombo.DoesNotExist):
            return Response({'success': False, 'error': 'Cart item not found'},
                            status=status.HTTP_404_NOT_FOUND)
        except Exception:
            logger.exception("Failed to update cart item")
            return Response({'success': False,
                             'error': 'Something went wrong while updating the item. Please try again.'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return self._cart_response(request)

    # ------------------------------------------------------------------
    # REMOVE ITEM
    # ------------------------------------------------------------------
    @action(detail=False, methods=['delete', 'post'])
    def remove_item(self, request):
        item_id = request.data.get('product_id') or request.data.get('id')

        if not item_id:
            return Response({'success': False, 'error': 'Item id required'},
                            status=status.HTTP_400_BAD_REQUEST)

        # Parse composite key if provided (e.g., "product-1" or "combo-1")
        if isinstance(item_id, str) and '-' in item_id:
            parts = item_id.split('-', 1)
            if len(parts) == 2:
                item_type, product_id = parts
            else:
                return Response({'success': False, 'error': 'Invalid item id format'},
                                status=status.HTTP_400_BAD_REQUEST)
        else:
            # Fallback to item_type parameter
            item_type = request.data.get('item_type', 'product')
            product_id = item_id

        # Validate item_type
        if item_type not in ('product', 'combo'):
            return Response({'success': False, 'error': "item_type must be 'product' or 'combo'"},
                            status=status.HTTP_400_BAD_REQUEST)

        # Validate product_id is a valid integer
        try:
            product_id = int(product_id)
        except (ValueError, TypeError):
            return Response({'success': False, 'error': 'Item id must be a valid integer'},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                cart = get_object_or_404(Cart, user=request.user)

                if item_type == 'combo':
                    cart_item = CartItem.objects.select_for_update().get(cart=cart, combo__id=product_id, item_type='combo')
                else:
                    variant_id = request.data.get('variant_id')
                    qs = CartItem.objects.select_for_update().filter(
                        cart=cart, product__id=product_id, item_type='product')
                    if variant_id:
                        qs = qs.filter(variant__id=variant_id)
                    # If multiple sizes of the same product are in the cart and no
                    # variant was specified, remove the first matching line.
                    cart_item = qs.first()
                    if cart_item is None:
                        raise CartItem.DoesNotExist()

                cart_item.delete()

        except CartItem.DoesNotExist:
            return Response({'success': False, 'error': 'Cart item not found'},
                            status=status.HTTP_404_NOT_FOUND)
        except Exception:
            logger.exception("Failed to remove cart item")
            return Response({'success': False,
                             'error': 'Something went wrong while removing the item. Please try again.'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return self._cart_response(request)

    # ------------------------------------------------------------------
    # CLEAR
    # ------------------------------------------------------------------
    @action(detail=False, methods=['post'])
    def clear(self, request):
        try:
            with transaction.atomic():
                cart = get_object_or_404(Cart, user=request.user)
                cart.items.all().delete()
        except Exception:
            logger.exception("Failed to clear cart")
            return Response({'success': False,
                             'error': 'Something went wrong while clearing the cart. Please try again.'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({'success': True, 'items': []})

    # ------------------------------------------------------------------
    # SYNC
    # ------------------------------------------------------------------
    @action(detail=False, methods=['post'])
    def sync(self, request):
        """Sync cart items from frontend to backend.
        
        IMPORTANT: Validates ALL items BEFORE clearing the cart.
        This prevents data loss if validation fails partway through.
        """
        items_data = request.data.get('items', [])

        # Validate items is a list
        if not isinstance(items_data, list):
            return Response({
                'success': False,
                'error': "'items' must be a list"
            }, status=status.HTTP_400_BAD_REQUEST)

        # Bound the payload size: a sync request can't carry an unbounded number
        # of items (memory/time DoS vector).
        if len(items_data) > MAX_SYNC_ITEMS:
            flag_suspicious(request, reason='cart.sync.size', value=len(items_data))
            return Response({
                'success': False,
                'error': f'Cannot sync more than {MAX_SYNC_ITEMS} items at once.'
            }, status=status.HTTP_400_BAD_REQUEST)

        # -----------------------------------------------------------
        # Phase 1: Validate all items and collect valid ones
        # -----------------------------------------------------------
        validated_items = []  # list of (item_obj, item_type, quantity, variant)
        skipped = []

        for item_data in items_data:
            try:
                product_id = item_data.get('product_id') or item_data.get('id')
                item_type = item_data.get('item_type', 'product')

                # Validate quantity
                raw_quantity = item_data.get('quantity', 1)
                try:
                    quantity = int(raw_quantity)
                    if quantity < 1:
                        skipped.append({
                            'id': str(product_id or 'unknown'),
                            'type': item_type,
                            'reason': 'quantity must be a positive integer'
                        })
                        continue
                    if quantity > MAX_ITEM_QUANTITY:
                        skipped.append({
                            'id': str(product_id or 'unknown'),
                            'type': item_type,
                            'reason': f'quantity exceeds the max of {MAX_ITEM_QUANTITY}'
                        })
                        continue
                except (ValueError, TypeError):
                    skipped.append({
                        'id': str(product_id or 'unknown'),
                        'type': item_type,
                        'reason': 'invalid quantity format'
                    })
                    continue

                if not product_id:
                    continue

                if item_type == 'combo':
                    try:
                        item = ProductCombo.objects.get(id=product_id, is_active=True)
                    except ProductCombo.DoesNotExist:
                        skipped.append({
                            'id': str(product_id),
                            'type': 'combo',
                            'reason': 'combo not found'
                        })
                        continue

                    stock = getattr(item, 'stock', 999)
                    if stock < quantity:
                        skipped.append({
                            'id': str(product_id),
                            'type': 'combo',
                            'reason': f'only {stock} available'
                        })
                        continue

                    validated_items.append((item, 'combo', quantity, None))

                else:
                    try:
                        item = Product.objects.get(id=product_id, is_active=True)
                    except Product.DoesNotExist:
                        skipped.append({
                            'id': str(product_id),
                            'type': 'product',
                            'reason': 'product not found'
                        })
                        continue

                    variant = _resolve_variant(item, item_data.get('variant_id'))
                    if item_data.get('variant_id') and variant is None:
                        skipped.append({
                            'id': str(product_id),
                            'type': 'product',
                            'reason': 'selected size unavailable'
                        })
                        continue

                    avail = variant.stock if variant else item.stock
                    if avail < quantity:
                        skipped.append({
                            'id': str(product_id),
                            'type': 'product',
                            'reason': f'only {avail} available'
                        })
                        continue

                    validated_items.append((item, 'product', quantity, variant))

            except ValueError as e:
                skipped.append({
                    'id': str(item_data.get('product_id', item_data.get('id', 'unknown'))),
                    'type': item_data.get('item_type', 'product'),
                    'reason': f'invalid data: {str(e)}'
                })
                continue
            except Exception:
                logger.exception("Failed to validate a cart sync item")
                skipped.append({
                    'id': str(item_data.get('product_id', item_data.get('id', 'unknown'))),
                    'type': item_data.get('item_type', 'product'),
                    'reason': 'unexpected error'
                })
                continue

        # -----------------------------------------------------------
        # Phase 2: Clear cart and insert validated items atomically
        # Only reached AFTER all items have been validated above.
        # -----------------------------------------------------------
        try:
            with transaction.atomic():
                cart, _ = Cart.objects.get_or_create(user=request.user)
                cart.items.all().delete()

                for item_obj, item_type, quantity, variant in validated_items:
                    if item_type == 'combo':
                        CartItem.objects.create(
                            cart=cart, combo=item_obj,
                            item_type='combo', quantity=quantity,
                        )
                    else:
                        CartItem.objects.create(
                            cart=cart, product=item_obj, variant=variant,
                            item_type='product', quantity=quantity,
                        )

        except Exception:
            logger.exception("Failed to sync cart")
            return Response({
                'success': False,
                'error': 'Failed to sync cart. Please try again.',
                'items': [],
                'skipped': []
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Fetch and return the updated cart via serializer
        response_data = self._cart_response(request).data
        response_data['skipped'] = skipped
        return Response(response_data)


class ValidateCouponAPIView(APIView):
    def post(self, request):
        serializer = ValidateCouponSerializer(data=request.data)
        if serializer.is_valid():
            code = serializer.validated_data['code']
            try:
                # Case-insensitive lookup so this matches checkout exactly — a
                # code that works at checkout must not be reported "does not
                # exist" here (and vice-versa).
                coupon = Coupon.objects.get(code__iexact=code)
            except Coupon.DoesNotExist:
                return Response({
                    'valid': False,
                    'message': f'"{code}" is not a valid coupon code.'
                }, status=status.HTTP_200_OK)

            # Validate against the user's actual cart total so the minimum-order
            # rule is honoured here too (instead of passing at validation and
            # then failing at checkout).
            cart = Cart.objects.filter(user=request.user).first()
            order_amount = cart.total_price if cart else None
            reason = coupon.get_invalid_reason(order_amount=order_amount)
            if reason:
                return Response({'valid': False, 'message': reason}, status=status.HTTP_200_OK)

            return Response({
                'valid': True,
                'message': 'Coupon applied.',
                'coupon_id': coupon.id,
                'discount_percent': coupon.discount_percent
            }, status=status.HTTP_200_OK)

        return Response({
            'valid': False,
            'message': 'Invalid request data.',
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)


class CartPaymentQRView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        cart, _ = Cart.objects.get_or_create(user=user)

        total_amount = Decimal(cart.total_price)
        summary = {
            "original": float(total_amount),
            "discount": 0.0,
            "final": float(total_amount),
        }

        coupon_code = request.data.get('coupon_code')
        discount_applied = 0

        if coupon_code:
            try:
                coupon = Coupon.objects.get(code=coupon_code)
                if coupon.is_valid(order_amount=total_amount):
                    discount_applied = coupon.discount_percent
                    discount_amount = (total_amount * Decimal(discount_applied) / Decimal(100)).quantize(Decimal('0.01'))
                    total_amount = (total_amount - discount_amount).quantize(Decimal('0.01'))
                    summary["discount"] = float(discount_amount)
                    summary["final"] = float(total_amount)
                else:
                    return Response({'success': False, 'error': 'Coupon expired or inactive.'},
                                    status=status.HTTP_400_BAD_REQUEST)
            except Coupon.DoesNotExist:
                return Response({'success': False, 'error': 'Invalid coupon code.'},
                                status=status.HTTP_400_BAD_REQUEST)

        if total_amount <= 0:
            return Response({'success': False, 'error': 'Cart is empty or total amount is invalid.'},
                            status=status.HTTP_400_BAD_REQUEST)

        acc_id = request.data.get("receivable_account_id")
        if not acc_id:
            return Response({'success': False, 'error': 'receivable_account_id is required.'},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            acc_id = int(acc_id)
        except (ValueError, TypeError):
            return Response({'success': False, 'error': 'receivable_account_id must be a valid integer'},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            account = ReceivableAccount.objects.get(id=acc_id, is_active=True)
        except ReceivableAccount.DoesNotExist:
            return Response({'success': False, 'error': 'Receivable account not found.'},
                            status=status.HTTP_404_NOT_FOUND)

        qr_base64, upi_url = generate_upi_qr_code(
            account=account,
            amount=total_amount,
            transaction_note=f"Cart Payment{f' (Coupon: {coupon_code})' if coupon_code else ''}"
        )

        return Response({
            'upi_url': upi_url,
            'amount': float(total_amount),
            'discount_percent': discount_applied,
            "summary": summary,
        })


class FavoritesViewSet(viewsets.ViewSet):
    """ViewSet for managing user favorites — fully serialized"""
    permission_classes = [IsAuthenticated]

    def list(self, request):
        """Get all favorites for the current user — via FavoriteItemSerializer"""
        favorites = Favorite.objects.filter(
            user=request.user,
            product__is_active=True,
        ).select_related('product')

        serializer = FavoriteItemSerializer(
            favorites,
            many=True,
            context={'request': request},
        )
        return Response(serializer.data)

    def create(self, request):
        """Add a product to favorites"""
        product_id = request.data.get('product_id')

        if not product_id:
            return Response({'success': False, 'error': 'product_id is required'},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            product_id = int(product_id)
        except (ValueError, TypeError):
            return Response({'success': False, 'error': 'product_id must be a valid integer'},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            product = Product.objects.get(id=product_id, is_active=True)

            # Check if already favorited
            fav, created = Favorite.objects.get_or_create(
                user=request.user,
                product=product
            )

            return Response({
                'success': True,
                'created': created,
                'message': 'Added to favorites' if created else 'Already in favorites'
            })

        except Product.DoesNotExist:
            return Response({'success': False, 'error': 'Product not found'},
                            status=status.HTTP_404_NOT_FOUND)
        except Exception:
            logger.exception("Failed to add favorite")
            return Response({'success': False,
                             'error': 'Something went wrong while adding the favorite. Please try again.'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def destroy(self, request, pk=None):
        """Remove a product from favorites"""
        try:
            fav = Favorite.objects.get(user=request.user, product_id=pk)
            fav.delete()
            return Response({'success': True, 'message': 'Removed from favorites'})
        except Favorite.DoesNotExist:
            return Response({'success': False, 'error': 'Favorite not found'},
                            status=status.HTTP_404_NOT_FOUND)
        except Exception:
            logger.exception("Failed to remove favorite")
            return Response({'success': False,
                             'error': 'Something went wrong while removing the favorite. Please try again.'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'])
    def sync(self, request):
        """Sync favorites from frontend to backend"""
        items_data = request.data.get('items', [])

        try:
            with transaction.atomic():
                # Get existing favorites
                existing_ids = set(
                    Favorite.objects.filter(user=request.user).values_list('product_id', flat=True)
                )

                incoming_ids = set()
                for item in items_data:
                    product_id = item.get('id') or item.get('product_id')
                    if product_id:
                        try:
                            incoming_ids.add(int(product_id))
                        except (ValueError, TypeError):
                            continue

                # Add new favorites in one batch. filter(is_active=True) drops
                # inactive/nonexistent ids (matching the old per-item
                # DoesNotExist skip); ignore_conflicts absorbs the unique
                # (user, product) constraint the way get_or_create did.
                to_add = incoming_ids - existing_ids
                if to_add:
                    valid_products = Product.objects.filter(id__in=to_add, is_active=True)
                    Favorite.objects.bulk_create(
                        [Favorite(user=request.user, product=p) for p in valid_products],
                        ignore_conflicts=True,
                    )

        except Exception:
            logger.exception("Failed to sync favorites")
            return Response({'success': False,
                             'error': 'Failed to sync favorites. Please try again.'},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Return updated favorites list via serializer
        return self.list(request)
