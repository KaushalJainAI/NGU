import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAdminData } from '@/hooks/useAdminData';
import { TableSkeleton } from '@/components/TableSkeleton';
import { 
  getContactSubmissions, 
  updateContactSubmission, 
  markContactAsRead,
  replyToContact,
  deleteContactSubmission,
  ContactSubmission 
} from '@/api/support';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from '@/hooks/use-toast';
import { Eye, Trash2, Mail, Reply, CheckCircle, RefreshCw } from 'lucide-react';
import { format } from 'date-fns';
import { PageHelp } from '@/components/PageHelp';
import { useTranslation } from 'react-i18next';

type StatusFilter = 'all' | 'new' | 'read' | 'replied' | 'closed';

const ContactSubmissions = () => {
  const { t } = useTranslation();
  const {
    data: submissions = [], isInitialLoading, refreshing, refetch,
  } = useAdminData(['contact-submissions'], async () => {
    const response = await getContactSubmissions();
    // Handle both array and paginated response
    return Array.isArray(response.data)
      ? response.data
      : ((response.data as any).results || []) as ContactSubmission[];
  });
  const [viewingSubmission, setViewingSubmission] = useState<ContactSubmission | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [replyDialogOpen, setReplyDialogOpen] = useState(false);
  const [replyNotes, setReplyNotes] = useState('');
  // The dashboard's "Read messages" card deep-links to /contact?status=new.
  const [searchParams] = useSearchParams();
  const [statusFilter, setStatusFilter] = useState<StatusFilter>(() => {
    const s = searchParams.get('status');
    return s === 'new' || s === 'read' || s === 'replied' || s === 'closed' ? s : 'all';
  });
  const { toast } = useToast();

  const handleMarkRead = async (submission: ContactSubmission) => {
    try {
      await markContactAsRead(submission.id);
      toast({ title: t('products.successTitle'), description: t('contact.markedRead') });
      refetch();
    } catch (error) {
      toast({
        title: t('common.error'),
        description: t('contact.markReadFailed'),
        variant: 'destructive',
      });
    }
  };

  const handleReply = async () => {
    if (!viewingSubmission) return;
    try {
      await replyToContact(viewingSubmission.id, replyNotes);
      toast({ title: t('products.successTitle'), description: t('contact.replySaved') });
      setReplyDialogOpen(false);
      setReplyNotes('');
      refetch();
    } catch (error) {
      toast({
        title: t('common.error'),
        description: t('contact.replySaveFailed'),
        variant: 'destructive',
      });
    }
  };

  const handleDelete = async (submission: ContactSubmission) => {
    if (!confirm(t('contact.deleteConfirm', { name: submission.name }))) return;
    try {
      await deleteContactSubmission(submission.id);
      toast({ title: t('products.successTitle'), description: t('contact.deleted') });
      refetch();
    } catch (error) {
      toast({
        title: t('common.error'),
        description: t('contact.deleteFailed'),
        variant: 'destructive',
      });
    }
  };

  const openViewDialog = (submission: ContactSubmission) => {
    setViewingSubmission(submission);
    setDialogOpen(true);
    // Auto-mark as read when viewing
    if (submission.status === 'new') {
      handleMarkRead(submission);
    }
  };

  const openReplyDialog = (submission: ContactSubmission) => {
    setViewingSubmission(submission);
    setReplyNotes(submission.admin_notes || '');
    setReplyDialogOpen(true);
  };

  const getStatusBadge = (status: string) => {
    const variants: Record<string, { variant: 'default' | 'secondary' | 'destructive' | 'outline', label: string }> = {
      new: { variant: 'default', label: t('contact.statusNew') },
      read: { variant: 'secondary', label: t('contact.statusRead') },
      replied: { variant: 'outline', label: t('contact.statusReplied') },
      closed: { variant: 'outline', label: t('contact.statusClosed') },
    };
    const config = variants[status] || { variant: 'outline', label: status };
    return <Badge variant={config.variant}>{config.label}</Badge>;
  };

  const filteredSubmissions = submissions.filter(s => 
    statusFilter === 'all' || s.status === statusFilter
  );

  const newCount = submissions.filter(s => s.status === 'new').length;

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold">{t('contact.title')}</h1>
          <p className="text-muted-foreground">
            {t('contact.subtitle')}
            {newCount > 0 && (
              <Badge variant="destructive" className="ml-2">
                {t('contact.newBadge', { count: newCount })}
              </Badge>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v as StatusFilter)}>
            <SelectTrigger className="w-[120px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t('common.all')}</SelectItem>
              <SelectItem value="new">{t('contact.statusNew')}</SelectItem>
              <SelectItem value="read">{t('contact.statusRead')}</SelectItem>
              <SelectItem value="replied">{t('contact.statusReplied')}</SelectItem>
              <SelectItem value="closed">{t('contact.statusClosed')}</SelectItem>
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            onClick={() => refetch()}
            disabled={refreshing}
          >
            <RefreshCw className={`h-4 w-4 mr-2 ${refreshing ? 'animate-spin' : ''}`} /> {t('common.refresh')}
          </Button>
        </div>
      </div>

      <PageHelp>{t('contact.pageHelp')}</PageHelp>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Mail className="h-5 w-5" />
            {t('contact.messagesTitle', { count: filteredSubmissions.length })}
          </CardTitle>
        </CardHeader>
        <CardContent
          className={`overflow-x-auto transition-opacity ${refreshing ? 'opacity-60' : 'opacity-100'}`}
        >
          {isInitialLoading ? <TableSkeleton rows={6} columns={6} /> : (
          <Table className="min-w-[700px]">
            <TableHeader>
              <TableRow>
                <TableHead>{t('common.name')}</TableHead>
                <TableHead>{t('common.email')}</TableHead>
                <TableHead>{t('contact.colSubject')}</TableHead>
                <TableHead>{t('common.status')}</TableHead>
                <TableHead>{t('common.date')}</TableHead>
                <TableHead className="text-right">{t('common.actions')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredSubmissions.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-muted-foreground">
                    {t('contact.empty')}
                  </TableCell>
                </TableRow>
              ) : (
                filteredSubmissions.map((submission) => (
                  <TableRow key={submission.id} className={submission.status === 'new' ? 'bg-primary/5' : ''}>
                    <TableCell className="font-medium">{submission.name}</TableCell>
                    <TableCell>{submission.email}</TableCell>
                    <TableCell className="max-w-[200px] truncate">{submission.subject}</TableCell>
                    <TableCell>{getStatusBadge(submission.status)}</TableCell>
                    <TableCell>{format(new Date(submission.created_at), 'dd MMM yyyy')}</TableCell>
                    <TableCell className="text-right space-x-1">
                      <Button variant="ghost" size="icon" onClick={() => openViewDialog(submission)} title={t('contact.viewTooltip')}>
                        <Eye className="h-4 w-4" />
                      </Button>
                      <Button variant="ghost" size="icon" onClick={() => openReplyDialog(submission)} title={t('contact.replyTooltip')}>
                        <Reply className="h-4 w-4" />
                      </Button>
                      {submission.status === 'new' && (
                        <Button variant="ghost" size="icon" onClick={() => handleMarkRead(submission)} title={t('contact.markReadTooltip')}>
                          <CheckCircle className="h-4 w-4" />
                        </Button>
                      )}
                      <Button 
                        variant="ghost" 
                        size="icon" 
                        onClick={() => handleDelete(submission)}
                        className="text-destructive hover:text-destructive"
                        title={t('contact.deleteTooltip')}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
          )}
        </CardContent>
      </Card>

      {/* View Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{t('contact.detailsTitle')}</DialogTitle>
            <DialogDescription>
              {t('contact.detailsFrom', {
                name: viewingSubmission?.name ?? '',
                when: viewingSubmission?.created_at
                  ? format(new Date(viewingSubmission.created_at), 'dd MMM yyyy, hh:mm a')
                  : '',
              })}
            </DialogDescription>
          </DialogHeader>
          {viewingSubmission && (
            <div className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <Label className="text-muted-foreground">{t('common.email')}</Label>
                  <p className="font-medium">{viewingSubmission.email}</p>
                </div>
                <div>
                  <Label className="text-muted-foreground">{t('common.phone')}</Label>
                  <p className="font-medium">{viewingSubmission.phone || t('orders.notAvailable')}</p>
                </div>
              </div>
              <div>
                <Label className="text-muted-foreground">{t('contact.colSubject')}</Label>
                <p className="font-medium">{viewingSubmission.subject}</p>
              </div>
              <div>
                <Label className="text-muted-foreground">{t('contact.message')}</Label>
                <p className="mt-1 p-3 bg-muted rounded-lg whitespace-pre-wrap">{viewingSubmission.message}</p>
              </div>
              {viewingSubmission.admin_notes && (
                <div>
                  <Label className="text-muted-foreground">{t('contact.adminNotes')}</Label>
                  <p className="mt-1 p-3 bg-green-50 dark:bg-green-950/30 rounded-lg text-green-800 dark:text-green-300 whitespace-pre-wrap">
                    {viewingSubmission.admin_notes}
                  </p>
                </div>
              )}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>{t('common.close')}</Button>
            <Button onClick={() => { setDialogOpen(false); openReplyDialog(viewingSubmission!); }}>
              <Reply className="h-4 w-4 mr-2" /> {t('contact.reply')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Reply Dialog */}
      <Dialog open={replyDialogOpen} onOpenChange={setReplyDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('contact.replyTitle', { name: viewingSubmission?.name ?? '' })}</DialogTitle>
            <DialogDescription>{t('contact.replyDescription')}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2 py-2">
            <Label htmlFor="reply-notes">{t('contact.adminNotes')}</Label>
            <Textarea
              id="reply-notes"
              value={replyNotes}
              onChange={(e) => setReplyNotes(e.target.value)}
              placeholder={t('contact.replyPlaceholder')}
              rows={6}
              className="min-h-[140px] resize-y"
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              className="gap-1.5 sm:mr-auto"
              onClick={() => setReplyNotes('')}
              disabled={!replyNotes}
            >
              <RefreshCw className="h-3.5 w-3.5" />
              {t('common.reset')}
            </Button>
            <Button variant="outline" onClick={() => setReplyDialogOpen(false)}>{t('common.cancel')}</Button>
            <Button onClick={handleReply}>{t('contact.saveReply')}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default ContactSubmissions;
