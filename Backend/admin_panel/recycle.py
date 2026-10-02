"""Recycle Bin for rows that are HARD-deleted by an admin.

`bin_and_delete` snapshots a row into `DeletedRecord` and then deletes it;
`restore_record` puts it back. Viewsets opt in with `RecycleBinDestroyMixin`.

What a snapshot holds
---------------------
* `objects` — the row itself and every row its deletion CASCADEs to, serialized
  with Django's own serializer (so every concrete column round-trips, including
  modeltranslation's per-language ones).
* `relinks` — foreign keys that deletion sets to NULL (e.g. `Order.coupon`).
  Without these a restored coupon would come back attached to no order, and the
  orders that used it would have lost their coupon code for good.

Restoring is all-or-nothing and refuses rather than guesses: if the primary key
has been reused, a unique value (a coupon code, a UPI id) has been taken by a
newer row, or something the row belonged to has itself been deleted, the caller
gets a `RestoreConflict` carrying a sentence an admin can act on.
"""
import json

from django.core import serializers
from django.db import IntegrityError, router, transaction
from django.db.models import SET_NULL
from django.db.models.deletion import Collector

from .models import DeletedRecord


class RestoreConflict(Exception):
    """The snapshot can no longer be put back as it was."""


def _collect(instance):
    """Every row deleting `instance` would remove, `instance` first."""
    collector = Collector(using=router.db_for_write(type(instance)))
    collector.collect([instance])
    rows = [instance]
    for objs in collector.data.values():
        rows.extend(o for o in objs if o is not instance)
    # Rows with no signals and no further cascades are queued as querysets
    # rather than instances — they are deleted all the same, so snapshot them.
    for queryset in collector.fast_deletes:
        rows.extend(queryset)
    return rows


def _set_null_links(instance):
    """Foreign keys that will be nulled when `instance` goes."""
    links = []
    for rel in instance._meta.related_objects:
        if rel.on_delete is not SET_NULL:
            continue
        model = rel.related_model
        pks = list(model._base_manager.filter(**{rel.field.name: instance})
                   .values_list('pk', flat=True))
        if pks:
            links.append({'model': model._meta.label_lower,
                          'field': rel.field.name, 'pks': pks})
    return links


def bin_and_delete(instance, *, kind, label, user=None, preview_url=''):
    """Move `instance` to the Recycle Bin. Returns the DeletedRecord."""
    with transaction.atomic():
        payload = {
            'objects': json.loads(serializers.serialize('json', _collect(instance))),
            'relinks': _set_null_links(instance),
        }
        record = DeletedRecord.objects.create(
            kind=kind,
            model_label=instance._meta.label_lower,
            object_pk=str(instance.pk),
            label=(label or str(instance))[:255],
            preview_url=(preview_url or '')[:500],
            payload=payload,
            deleted_by=user if getattr(user, 'is_authenticated', False) else None,
        )
        instance.delete()
    return record


def _check_restorable(obj, incoming):
    """Raise RestoreConflict if `obj` cannot go back; detach dead optional FKs."""
    model = type(obj)
    name = model._meta.verbose_name
    if model._base_manager.filter(pk=obj.pk).exists():
        raise RestoreConflict(f'This {name} already exists — it may have been '
                              f'restored already.')
    for field in model._meta.concrete_fields:
        if not field.is_relation:
            continue
        value = getattr(obj, field.attname)
        if value is None:
            continue
        target = field.related_model
        if (target._meta.label_lower, str(value)) in incoming:
            continue  # restored in this same batch
        if target._base_manager.filter(pk=value).exists():
            continue
        if field.null:
            setattr(obj, field.attname, None)  # e.g. the user who wrote it left
        else:
            raise RestoreConflict(
                f'The {target._meta.verbose_name} this {name} belonged to no '
                f'longer exists, so it cannot be restored.')


def restore_record(record):
    """Put a binned row back and drop its bin entry. Returns the restored row."""
    from django.apps import apps

    try:
        with transaction.atomic():
            deserialized = list(serializers.deserialize(
                'json', json.dumps(record.payload.get('objects') or [])))
            if not deserialized:
                raise RestoreConflict('This entry is empty and cannot be restored.')
            incoming = {(type(d.object)._meta.label_lower, str(d.object.pk))
                        for d in deserialized}
            for item in deserialized:
                _check_restorable(item.object, incoming)
            # Raw save: keeps the original created_at/updated_at and primary key
            # instead of re-running auto_now and custom save() side effects.
            for item in deserialized:
                item.save()

            restored = deserialized[0].object
            for link in record.payload.get('relinks') or []:
                model = apps.get_model(link['model'])
                # Only rows still unattached — one re-pointed since is left alone.
                model._base_manager.filter(
                    pk__in=link['pks'], **{f"{link['field']}__isnull": True}
                ).update(**{link['field']: restored})

            _after_restore(restored)
            record.delete()
    except IntegrityError:
        raise RestoreConflict(
            'A newer record now uses the same unique value (for example the '
            'same code or UPI ID). Change or delete that one first.')
    return restored


def _after_restore(obj):
    """Invariants a raw save does not re-establish."""
    from .models import ReceivableAccount
    # Only one account may be the default. One deleted while it was the default
    # must not steal that back from whichever account has replaced it.
    if isinstance(obj, ReceivableAccount) and obj.is_default:
        if ReceivableAccount.objects.filter(is_default=True).exclude(pk=obj.pk).exists():
            ReceivableAccount.objects.filter(pk=obj.pk).update(is_default=False)


class RecycleBinDestroyMixin:
    """DELETE moves the row to the Recycle Bin instead of destroying it.

    Set `recycle_kind`; override `recycle_label` for what the bin should call
    the row, `recycle_preview_url` for a thumbnail, and `should_recycle` to let
    some deletes through untouched (a customer removing their own review).
    """
    recycle_kind = None

    def recycle_label(self, instance):
        return str(instance)

    def recycle_preview_url(self, instance):
        return ''

    def should_recycle(self, instance):
        return True

    def perform_destroy(self, instance):
        if not self.should_recycle(instance):
            return super().perform_destroy(instance)
        bin_and_delete(
            instance,
            kind=self.recycle_kind,
            label=self.recycle_label(instance),
            user=self.request.user,
            preview_url=self.recycle_preview_url(instance),
        )
