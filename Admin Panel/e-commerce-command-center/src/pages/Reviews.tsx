import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  getAllReviews, getFeaturedReviews, setReviewHidden, setReviewFeatured, deleteReview,
  Review, PaginatedReviews, MAX_FEATURED_REVIEWS,
} from '@/api/reviews';
import { useAdminData } from '@/hooks/useAdminData';
import { TableSkeleton } from '@/components/TableSkeleton';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { useToast } from '@/hooks/use-toast';
import { Star, EyeOff, Eye, Trash2, Home } from 'lucide-react';
import { PageHelp } from '@/components/PageHelp';
import { useTranslation } from 'react-i18next';

const PAGE_SIZE = 12; // matches backend REST_FRAMEWORK PAGE_SIZE

/** Normalise the paginated-or-plain-array list shape the API may return. */
const toRows = (data: PaginatedReviews | Review[]) =>
  Array.isArray(data)
    ? { results: data, count: data.length }
    : { results: data.results || [], count: data.count || 0 };

const Stars = ({ rating }: { rating: number }) => (
  <span className="inline-flex">
    {[1, 2, 3, 4, 5].map(i => (
      <Star key={i} className={`h-4 w-4 ${i <= rating ? 'fill-amber-400 text-amber-400' : 'text-muted-foreground/30'}`} />
    ))}
  </span>
);

const Reviews = () => {
  const { t } = useTranslation();
  const [page, setPage] = useState(1);
  const { toast } = useToast();
  const queryClient = useQueryClient();

  // Keyed by page, so paging back to a page already seen is instant.
  const queryKey = ['reviews', page];
  const { data, isInitialLoading, refreshing, refetch: fetchReviews } = useAdminData(
    queryKey,
    async () => toRows((await getAllReviews(page)).data),
  );
  const reviews = data?.results ?? [];
  const totalCount = data?.count ?? 0;

  // The pinned set, fetched separately so the "n of 3" counter and the picked
  // state stay right even when the three live on different pages of the table.
  const featuredKey = ['reviews', 'featured'];
  const { data: featuredData } = useAdminData(
    featuredKey,
    async () => toRows((await getFeaturedReviews()).data),
  );
  const featuredIds = new Set((featuredData?.results ?? []).map(r => r.id));
  const featuredCount = featuredIds.size;
  const slotsFull = featuredCount >= MAX_FEATURED_REVIEWS;

  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE));

  const toggleFeatured = async (review: Review) => {
    const picking = !featuredIds.has(review.id);
    try {
      await setReviewFeatured(review.id, picking);
      // Both lists change: the row's own pill and the slot counter.
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: featuredKey }),
        queryClient.invalidateQueries({ queryKey }),
      ]);
      toast({
        title: picking ? t('reviews.addedTitle') : t('reviews.removedTitle'),
        description: picking ? t('reviews.addedBody') : t('reviews.removedBody'),
      });
    } catch (e) {
      toast({
        title: t('reviews.featureFailedTitle'),
        description: e instanceof Error ? e.message : t('reviews.tryAgain'),
        variant: 'destructive',
      });
    }
  };

  const toggleHidden = async (review: Review) => {
    const hiding = !review.is_hidden;
    if (hiding && !confirm(t('reviews.confirmHide', { name: review.item_name }))) return;
    try {
      await setReviewHidden(review.id, hiding);
      // Patch the cached row in place: the toggle is instant and the table
      // never reloads for a one-field change.
      queryClient.setQueryData(queryKey, (prev: typeof data) => prev && {
        ...prev,
        results: prev.results.map(r => (r.id === review.id
          ? { ...r, is_hidden: hiding, is_featured: hiding ? false : r.is_featured }
          : r)),
      });
      // Hiding also releases the home page slot server-side, so the pinned
      // list has to be re-read or the counter would over-count.
      if (hiding) queryClient.invalidateQueries({ queryKey: featuredKey });
      toast({
        title: hiding ? t('reviews.hiddenTitle') : t('reviews.visibleTitle'),
        description: hiding ? t('reviews.hiddenBody') : t('reviews.visibleBody'),
      });
    } catch {
      toast({
        title: t('common.error'),
        description: t('reviews.updateFailed'),
        variant: 'destructive',
      });
    }
  };

  const handleDelete = async (review: Review) => {
    if (!confirm(t('reviews.confirmDelete', { name: review.item_name }))) return;
    try {
      await deleteReview(review.id);
      toast({ title: t('reviews.deletedTitle'), description: t('reviews.deletedBody') });
      fetchReviews();
      queryClient.invalidateQueries({ queryKey: featuredKey });
    } catch {
      toast({
        title: t('common.error'),
        description: t('reviews.deleteFailed'),
        variant: 'destructive',
      });
    }
  };

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">{t('reviews.title')}</h1>
        <p className="text-muted-foreground">
          {t('reviews.subtitle', { max: MAX_FEATURED_REVIEWS })}
        </p>
      </div>

      <PageHelp>{t('reviews.pageHelp')}</PageHelp>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4 space-y-0">
          <CardTitle>{t('reviews.allReviews')}</CardTitle>
          <span
            className={`text-sm rounded-full border px-3 py-1 ${
              slotsFull ? 'text-amber-600 border-amber-300 bg-amber-50 dark:bg-amber-950/30' : 'text-muted-foreground'
            }`}
            title={slotsFull
              ? t('reviews.slotsFullTitle', { max: MAX_FEATURED_REVIEWS })
              : t('reviews.slotsTitle')}
          >
            <Home className="inline h-3.5 w-3.5 mr-1.5 -mt-0.5" />
            {t('reviews.slotCounter', { count: featuredCount, max: MAX_FEATURED_REVIEWS })}
          </span>
        </CardHeader>
        <CardContent
          className={`overflow-x-auto transition-opacity ${refreshing ? 'opacity-60' : 'opacity-100'}`}
        >
          {isInitialLoading ? <TableSkeleton rows={6} columns={6} /> : (
          <>
          <Table className="min-w-[700px]">
            <TableHeader>
              <TableRow>
                <TableHead>{t('reviews.colProduct')}</TableHead>
                <TableHead>{t('reviews.colRating')}</TableHead>
                <TableHead>{t('reviews.colReview')}</TableHead>
                <TableHead>{t('reviews.colCustomer')}</TableHead>
                <TableHead>{t('reviews.colDate')}</TableHead>
                <TableHead>{t('reviews.colShown')}</TableHead>
                <TableHead>{t('reviews.colHome')}</TableHead>
                <TableHead className="text-right">{t('common.actions')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {reviews.length === 0 && (
                <TableRow>
                  <TableCell colSpan={8} className="text-center text-muted-foreground py-8">
                    {t('reviews.empty')}
                  </TableCell>
                </TableRow>
              )}
              {reviews.map(review => (
                <TableRow key={review.id} className={review.is_hidden ? 'opacity-60' : undefined}>
                  <TableCell className="font-medium">{review.item_name}</TableCell>
                  <TableCell><Stars rating={review.rating} /></TableCell>
                  <TableCell className="max-w-[280px]">
                    <p className="font-medium truncate">{review.title}</p>
                    {review.comment && (
                      <p className="text-xs text-muted-foreground line-clamp-2">{review.comment}</p>
                    )}
                  </TableCell>
                  <TableCell>{review.user_name}</TableCell>
                  <TableCell>{new Date(review.created_at).toLocaleDateString('en-IN')}</TableCell>
                  <TableCell>
                    {review.is_hidden
                      ? <span className="text-muted-foreground text-sm">{t('reviews.hidden')}</span>
                      : <span className="text-green-600 text-sm">{t('reviews.shown')}</span>}
                  </TableCell>
                  <TableCell>
                    {/* Radio-style picker: click to put this review on the home
                        page, click again to take it off. Disabled once all
                        slots are taken (unless this is one of them) and for
                        hidden reviews, which shoppers can't see anyway. */}
                    {(() => {
                      const picked = featuredIds.has(review.id);
                      const blocked = review.is_hidden || (slotsFull && !picked);
                      const label = review.is_hidden
                        ? t('reviews.pickHiddenBlocked')
                        : slotsFull && !picked
                          ? t('reviews.pickSlotsFull', { max: MAX_FEATURED_REVIEWS })
                          : picked
                            ? t('reviews.pickRemove')
                            : t('reviews.pickAdd');
                      return (
                        <button
                          type="button"
                          role="radio"
                          aria-checked={picked}
                          aria-label={label}
                          title={label}
                          disabled={blocked}
                          onClick={() => toggleFeatured(review)}
                          className={`flex items-center gap-2 text-sm rounded-md px-1 py-0.5 transition-colors ${
                            blocked ? 'opacity-40 cursor-not-allowed' : 'hover:text-foreground cursor-pointer'
                          } ${picked ? 'text-primary font-medium' : 'text-muted-foreground'}`}
                        >
                          <span
                            className={`h-4 w-4 shrink-0 rounded-full border-2 grid place-items-center ${
                              picked ? 'border-primary' : 'border-muted-foreground/40'
                            }`}
                          >
                            {picked && <span className="h-2 w-2 rounded-full bg-primary" />}
                          </span>
                          {picked ? t('reviews.onHomePage') : t('reviews.notShown')}
                        </button>
                      );
                    })()}
                  </TableCell>
                  <TableCell className="text-right">
                    <Button variant="ghost" size="icon" onClick={() => toggleHidden(review)}
                      title={review.is_hidden ? t('reviews.showInStore') : t('reviews.hideFromStore')}>
                      {review.is_hidden
                        ? <Eye className="h-4 w-4 text-green-600" />
                        : <EyeOff className="h-4 w-4 text-amber-600" />}
                    </Button>
                    <Button variant="ghost" size="icon" onClick={() => handleDelete(review)}
                      title={t('reviews.deletePermanently')}>
                      <Trash2 className="h-4 w-4 text-destructive" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          {totalPages > 1 && (
            <div className="flex items-center justify-between pt-4">
              <p className="text-sm text-muted-foreground">
                {t('reviews.pager', { page, total: totalPages, count: totalCount })}
              </p>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>
                  {t('common.previous')}
                </Button>
                <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>
                  {t('common.next')}
                </Button>
              </div>
            </div>
          )}
          </>
          )}
        </CardContent>
      </Card>
    </div>
  );
};

export default Reviews;
