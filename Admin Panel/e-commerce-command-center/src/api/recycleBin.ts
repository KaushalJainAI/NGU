import api from './axiosInstance';

/** What kind of row a bin entry was before it was deleted. */
export type RecycleKind =
  | 'coupon'
  | 'review'
  | 'expense'
  | 'product_image'
  | 'receivable_account'
  | 'contact_submission';

/**
 * One hard-deleted row waiting in the Recycle Bin. Products, combos and orders
 * are NOT here — they are soft-deleted on their own tables and listed from
 * their own endpoints. This is everything else an admin can delete.
 */
export interface RecycleBinItem {
  id: number;
  kind: RecycleKind | string;
  label: string;
  /** Thumbnail for an image entry; '' otherwise. */
  preview_url: string;
  deleted_at: string;
  deleted_by: string | null;
  /** When the nightly purge will drop it; null if purging is switched off. */
  purge_at: string | null;
}

export interface RecycleBinResponse {
  retention_days: number;
  items: RecycleBinItem[];
}

export const getRecycleBin = async () => {
  const response = await api.get<RecycleBinResponse>('/admin/recycle-bin/');
  return response.data;
};

/** Puts the row back under its original id. 409 (with a reason in
 *  `error.message`) if it can no longer be restored as it was. */
export const restoreRecycleBinItem = async (id: number) => {
  const response = await api.post<{ success: boolean; kind: string; label: string }>(
    `/admin/recycle-bin/${id}/restore/`,
  );
  return response.data;
};
