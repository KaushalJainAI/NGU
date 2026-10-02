import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Command as CommandPrimitive } from "cmdk";
import { Loader2, Mic, MicOff, Search, X } from "lucide-react";
import { toast } from "sonner";
import { Command, CommandItem, CommandList } from "@/components/ui/command";
import { cn } from "@/lib/utils";
import { searchAPI, Suggestion } from "@/lib/api/search";
import { matchPages } from "@/lib/searchablePages";
import { LANG_STORAGE_KEY } from "@/i18n/index";
import { useVoiceInput } from "@/hooks/useVoiceInput";
import { useTranslation } from "react-i18next";

interface SearchAutocompleteProps {
  inputClassName?: string;
  placeholder?: string;
}

/** How long the closing animation runs before the dropdown actually unmounts.
 *  Must stay in step with the `animate-out` duration below, or the panel either
 *  snaps away mid-fade or lingers as a dead overlay. */
const EXIT_MS = 150;

/** Per-row entrance offset. Small enough that a full list still feels instant
 *  (10 rows = 180ms), large enough to read as a cascade rather than a flash. */
const STAGGER_MS = 20;

const SearchAutocomplete = ({
  inputClassName = "",
  placeholder,
}: SearchAutocompleteProps) => {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(query.trim()), 250);
    return () => clearTimeout(timer);
  }, [query]);

  const lang = localStorage.getItem(LANG_STORAGE_KEY) ?? "en";

  // AP11: mic in the search bar — one utterance fills the box (reuses the
  // chat voice hook; silence stops it, errors toast instead of vanishing).
  const {
    supported: voiceSupported, recording: voiceRecording,
    transcribing: voiceTranscribing, error: voiceError, clearError: clearVoiceError,
    start: voiceStart, stop: voiceStop,
  } = useVoiceInput(
    (text) => {
      setQuery(text);
      setOpen(true);
      inputRef.current?.focus();
    },
    () => localStorage.getItem(LANG_STORAGE_KEY) ?? "en",
  );

  useEffect(() => {
    if (!voiceError) return;
    const key =
      voiceError === "mic-denied"
        ? "assistant.voiceMicDenied"
        : voiceError === "transcribe-failed"
          ? "assistant.voiceTranscribeFailed"
          : "assistant.voiceNothingHeard";
    const fallback =
      voiceError === "mic-denied"
        ? "Microphone blocked — allow mic access to use voice."
        : voiceError === "transcribe-failed"
          ? "Could not transcribe that — please try again."
          : "Didn't catch that — please try again.";
    toast.error(t(key, fallback));
    clearVoiceError();
  }, [voiceError, t, clearVoiceError]);

  const { data, isFetching } = useQuery({
    queryKey: ["suggest", lang, debouncedQuery],
    queryFn: () => searchAPI.suggest(debouncedQuery),
    enabled: debouncedQuery.length >= 2,
    staleTime: 60_000,
  });

  const suggestions: Suggestion[] =
    debouncedQuery.length >= 2 ? data?.suggestions ?? [] : [];

  // Client-side matches for navigable pages (cart, policies, orders, …) so the
  // search box also acts as a "go to page" jump list, not just product search.
  const pageMatches =
    debouncedQuery.length >= 2 ? matchPages(debouncedQuery) : [];

  // Close the dropdown on navigation. On the search results page keep the box
  // populated with the active query (so it's visible / editable); everywhere
  // else reset it after navigating to a result.
  useEffect(() => {
    setOpen(false);
    if (location.pathname === "/search") {
      const params = new URLSearchParams(location.search);
      setQuery(params.get("q") ?? params.get("search") ?? "");
    } else {
      setQuery("");
    }
  }, [location.pathname, location.search]);

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const goToSearchPage = () => {
    const q = query.trim();
    if (q) {
      navigate(`/search?q=${encodeURIComponent(q)}`);
    }
  };

  const goToSuggestion = (s: Suggestion) => {
    navigate(s.type === "combo" ? `/combos/${s.slug}` : `/products/${s.slug}`);
  };

  const showDropdown = open && query.trim().length >= 2;

  // Keep the panel mounted through its exit animation. Without this the
  // dropdown is torn out of the DOM the instant it closes, which reads as a
  // glitch next to how softly it arrives.
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    if (showDropdown) {
      setMounted(true);
      return;
    }
    if (!mounted) return;
    const timer = setTimeout(() => setMounted(false), EXIT_MS);
    return () => clearTimeout(timer);
  }, [showDropdown, mounted]);

  // Waiting on the first results for THIS query — the box would otherwise sit
  // empty (or show the previous query's hits) for the whole round trip.
  const isLoadingFresh =
    isFetching && suggestions.length === 0 && pageMatches.length === 0;

  // Rows animate in sequence. cmdk re-renders the list on every keystroke, so
  // the delay is keyed off the row's position and restarts with each new set —
  // which is the intent: a fresh result set should read as a fresh cascade.
  const rowStyle = (index: number) => ({
    animationDelay: `${index * STAGGER_MS}ms`,
    animationFillMode: "both" as const,
  });

  const rowAnimation =
    "animate-in fade-in-0 slide-in-from-top-1 duration-200 ease-out " +
    "motion-reduce:animate-none";

  // Where each block starts in the cascade. The pages block, when present,
  // costs its own heading plus the "Products" heading that follows it.
  const productOffset = pageMatches.length ? pageMatches.length + 2 : 0;
  const searchAllIndex = productOffset + suggestions.length;

  return (
    <div ref={containerRef} className="group relative">
      <Command
        shouldFilter={false}
        className="overflow-visible bg-transparent"
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            setOpen(false);
            (e.target as HTMLElement).blur();
          }
        }}
      >
        <div className="relative">
          {/* Icon slot: the magnifier cross-fades into a spinner while results
              are in flight, so the wait is visible without adding a row of
              chrome or shifting anything around it. */}
          <span className="pointer-events-none absolute left-4 top-1/2 z-10 grid h-4 w-4 -translate-y-1/2 place-items-center">
            <Search
              className={cn(
                "col-start-1 row-start-1 h-4 w-4 text-primary transition-all duration-300 ease-out motion-reduce:transition-none",
                "group-focus-within:scale-110",
                isFetching ? "scale-50 opacity-0" : "scale-100 opacity-100",
              )}
            />
            <Loader2
              className={cn(
                "col-start-1 row-start-1 h-4 w-4 animate-spin text-primary transition-all duration-300 ease-out motion-reduce:transition-none",
                isFetching ? "scale-100 opacity-100" : "scale-50 opacity-0",
              )}
            />
          </span>

          <CommandPrimitive.Input
            ref={inputRef}
            value={query}
            onValueChange={(value) => {
              setQuery(value);
              setOpen(true);
            }}
            onFocus={() => setOpen(true)}
            onKeyDown={(e) => {
              // cmdk handles arrows + Enter on highlighted items; plain Enter
              // with nothing highlighted falls through to the search page.
              if (e.key === "Enter" && !showDropdown) {
                e.preventDefault();
                goToSearchPage();
              }
            }}
            placeholder={placeholder ?? t('nav.search')}
            className={cn(
              "flex h-10 w-full rounded-full border border-border bg-card pl-10 py-1 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:border-primary hover:border-primary/50",
              // Focus lifts the pill slightly and warms its shadow. `transition-all`
              // was already here but had nothing but the ring to animate.
              "transition-all duration-300 ease-out motion-reduce:transition-none",
              "focus-visible:shadow-[0_6px_20px_-8px_hsl(var(--primary)/0.45)]",
              // Room for the clear button once there is something to clear.
              query ? "pr-10" : "pr-4",
              inputClassName,
            )}
          />

          {voiceSupported && !query && (
            <button
              type="button"
              aria-label={t('assistant.speak', 'Speak')}
              onClick={() => (voiceRecording ? voiceStop() : void voiceStart())}
              disabled={voiceTranscribing}
              className={cn(
                "absolute right-3 top-1/2 z-10 grid h-5 w-5 -translate-y-1/2 place-items-center rounded-full",
                "text-muted-foreground hover:bg-muted hover:text-foreground",
                voiceRecording && "animate-pulse text-primary",
              )}
            >
              {voiceTranscribing ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : voiceRecording ? (
                <MicOff className="h-3.5 w-3.5" />
              ) : (
                <Mic className="h-3.5 w-3.5" />
              )}
            </button>
          )}

          {query && (
            <button
              type="button"
              aria-label={t('search.clear')}
              onClick={() => {
                setQuery("");
                setOpen(false);
                inputRef.current?.focus();
              }}
              className={cn(
                "absolute right-3 top-1/2 z-10 grid h-5 w-5 -translate-y-1/2 place-items-center rounded-full",
                "text-muted-foreground hover:bg-muted hover:text-foreground",
                "transition-all duration-200 ease-out hover:rotate-90 motion-reduce:transition-none motion-reduce:hover:rotate-0",
                "animate-in fade-in-0 zoom-in-50 duration-150 motion-reduce:animate-none",
              )}
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>

        {mounted && (
          <div
            className={cn(
              "absolute top-full left-0 right-0 mt-2 z-50 origin-top rounded-2xl border border-border bg-popover text-popover-foreground shadow-xl overflow-hidden",
              showDropdown
                ? "animate-in fade-in-0 zoom-in-95 slide-in-from-top-2 duration-200 ease-out"
                : "pointer-events-none animate-out fade-out-0 zoom-out-95 slide-out-to-top-1 duration-150 ease-in",
              "motion-reduce:animate-none",
            )}
          >
            <CommandList>
              {isLoadingFresh ? (
                // Three placeholder rows in the real row geometry, so the panel
                // opens at roughly its final height instead of snapping taller
                // when the results land.
                <div className="p-1" aria-label={t('search.searching')} role="status">
                  {[0, 1, 2].map((i) => (
                    <div
                      key={`skeleton-${i}`}
                      className={cn("flex items-center gap-3 px-3 py-2", rowAnimation)}
                      style={rowStyle(i)}
                    >
                      <div className="h-9 w-9 flex-shrink-0 rounded-full animate-shimmer motion-reduce:animate-none" />
                      <div className="flex flex-1 flex-col gap-1.5">
                        <div className="h-3 w-2/5 rounded animate-shimmer motion-reduce:animate-none" />
                        <div className="h-2.5 w-1/4 rounded animate-shimmer motion-reduce:animate-none" />
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <>
                  {pageMatches.length > 0 && (
                    <>
                      <div
                        className={cn(
                          "px-3 pt-2 pb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground",
                          rowAnimation,
                        )}
                        style={rowStyle(0)}
                      >
                        {t('search.pages')}
                      </div>
                      {pageMatches.map((p, i) => (
                        <CommandItem
                          key={`page-${p.path}`}
                          value={`page-${p.path}`}
                          onSelect={() => navigate(p.path)}
                          className={cn(
                            "group/item cursor-pointer gap-3 px-3 py-2",
                            "transition-transform duration-200 ease-out data-[selected=true]:translate-x-1 motion-reduce:transition-none motion-reduce:data-[selected=true]:translate-x-0",
                            rowAnimation,
                          )}
                          style={rowStyle(i + 1)}
                        >
                          <span className="grid h-9 w-9 flex-shrink-0 place-items-center rounded-full bg-primary/10 text-primary transition-transform duration-300 ease-out group-hover/item:scale-110 group-data-[selected=true]/item:scale-110 motion-reduce:transition-none">
                            <p.icon className="h-4 w-4" />
                          </span>
                          <span className="flex flex-1 flex-col truncate notranslate">
                            <span className="truncate">{p.title}</span>
                            <span className="truncate text-xs text-muted-foreground">
                              {p.description}
                            </span>
                          </span>
                        </CommandItem>
                      ))}
                      {suggestions.length > 0 && (
                        <div
                          className={cn(
                            "px-3 pt-2 pb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground border-t border-border",
                            rowAnimation,
                          )}
                          style={rowStyle(pageMatches.length + 1)}
                        >
                          {t('search.products')}
                        </div>
                      )}
                    </>
                  )}
                  {suggestions.map((s, i) => (
                    <CommandItem
                      key={`${s.type}-${s.id}`}
                      value={`${s.type}-${s.id}`}
                      onSelect={() => goToSuggestion(s)}
                      className={cn(
                        "group/item cursor-pointer gap-3 px-3 py-2",
                        "transition-transform duration-200 ease-out data-[selected=true]:translate-x-1 motion-reduce:transition-none motion-reduce:data-[selected=true]:translate-x-0",
                        rowAnimation,
                      )}
                      style={rowStyle(productOffset + i)}
                    >
                      {s.image ? (
                        <span className="h-9 w-9 flex-shrink-0 overflow-hidden rounded-full spice-backdrop">
                          <img
                            src={s.image}
                            alt=""
                            className="h-full w-full object-contain p-0.5 transition-transform duration-300 ease-out group-hover/item:scale-110 group-data-[selected=true]/item:scale-110 motion-reduce:transition-none"
                          />
                        </span>
                      ) : (
                        <div className="h-9 w-9 rounded-full spice-backdrop flex-shrink-0" />
                      )}
                      <span className="flex-1 truncate notranslate">{s.name}</span>
                      <span className="text-sm font-semibold text-primary notranslate transition-transform duration-200 ease-out group-hover/item:scale-105 motion-reduce:transition-none">
                        ₹{s.price}
                      </span>
                    </CommandItem>
                  ))}
                  <CommandItem
                    key="search-all"
                    value="search-all"
                    onSelect={goToSearchPage}
                    className={cn(
                      "group/item cursor-pointer gap-2 px-3 py-2 border-t border-border text-muted-foreground",
                      "transition-colors duration-200 data-[selected=true]:text-foreground motion-reduce:transition-none",
                      rowAnimation,
                    )}
                    style={rowStyle(searchAllIndex)}
                  >
                    <Search className="h-4 w-4 flex-shrink-0 transition-transform duration-300 ease-out group-hover/item:scale-110 group-data-[selected=true]/item:scale-110 motion-reduce:transition-none" />
                    <span className="truncate">{t('search.searchFor', { query: query.trim() })}</span>
                  </CommandItem>
                </>
              )}
            </CommandList>
          </div>
        )}
      </Command>
    </div>
  );
};

export default SearchAutocomplete;
