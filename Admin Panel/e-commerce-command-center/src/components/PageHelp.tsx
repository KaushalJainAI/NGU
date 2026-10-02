import { HelpCircle } from 'lucide-react';

/** One plain-English line under a page title telling a non-technical admin what
 *  the page is for. Keep the text short and free of jargon. */
export const PageHelp = ({ children }: { children: React.ReactNode }) => (
  <div className="flex items-start gap-2 rounded-lg border border-dashed bg-muted/40 p-3 text-sm text-muted-foreground">
    <HelpCircle className="mt-0.5 h-4 w-4 flex-shrink-0" />
    <span>{children}</span>
  </div>
);
