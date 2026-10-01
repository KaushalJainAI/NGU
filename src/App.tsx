import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { toast } from "sonner";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Suspense, lazy } from "react";
import { AuthProvider } from "@/contexts/AuthContext";
import ProtectedRoute from "@/components/ProtectedRoute";
import AdminLayout from "@/components/AdminLayout";
import { RouteFallback } from "@/components/RouteFallback";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import NotFound from "./pages/NotFound";

// Every page below the layout is code-split. The admin lands on the dashboard,
// so shipping Products' image editor, Insights' charting library and the rest
// in the same bundle only delays the screen they actually asked for. Dashboard
// and Login stay eager — they are the first paint.
const Insights = lazy(() => import("./pages/Insights"));
const Products = lazy(() => import("./pages/Products"));
const Categories = lazy(() => import("./pages/Categories"));
const Sections = lazy(() => import("./pages/Sections"));
const Reviews = lazy(() => import("./pages/Reviews"));
const BulkEdit = lazy(() => import("./pages/BulkEdit"));
const Combos = lazy(() => import("./pages/Combos"));
const Orders = lazy(() => import("./pages/Orders"));
const Customers = lazy(() => import("./pages/Customers"));
const RecycleBin = lazy(() => import("./pages/RecycleBin"));
const Coupons = lazy(() => import("./pages/Coupons"));
const AdminInfo = lazy(() => import("./pages/AdminInfo"));
const ContactSubmissions = lazy(() => import("./pages/ContactSubmissions"));
const Conversations = lazy(() => import("./pages/Conversations"));
const GstReport = lazy(() => import("./pages/GstReport"));
const Accounts = lazy(() => import("./pages/Accounts"));

const queryClient = new QueryClient({
  // One place for load failures. Pages used to toast from inside their own
  // catch blocks; with the fetching centralised, this keeps that feedback
  // without every page re-implementing it. A background revalidation that
  // fails over data already on screen stays quiet — the stale rows are still
  // useful and a toast per retry would be noise.
  queryCache: new QueryCache({
    onError: (error, query) => {
      if (query.state.data !== undefined) return;
      toast.error(error instanceof Error && error.message
        ? error.message
        : 'Could not load this page. Check your connection and try again.');
    },
  }),
  defaultOptions: {
    queries: {
      // Treat data as fresh for 30s: clicking between Orders and Products and
      // back re-renders from cache instantly instead of refetching each time.
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      // The admin panel is a work tool that sits open next to other tabs —
      // refetching on every focus change is noise, not freshness.
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

/** One Suspense boundary per route, so a chunk load never blanks the layout. */
const page = (element: React.ReactNode) => (
  <Suspense fallback={<RouteFallback />}>{element}</Suspense>
);

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <BrowserRouter basename="/panel">
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route
              path="/"
              element={
                <ProtectedRoute>
                  <AdminLayout />
                </ProtectedRoute>
              }
            >
              {/* Index route, so "/" resolves inside the layout instead of
                  competing with it as a second route at the same path. */}
              <Route index element={<Navigate to="/dashboard" replace />} />
              <Route path="dashboard" element={<Dashboard />} />
              <Route path="insights" element={page(<Insights />)} />
              <Route path="products" element={page(<Products />)} />
              <Route path="categories" element={page(<Categories />)} />
              <Route path="sections" element={page(<Sections />)} />
              <Route path="reviews" element={page(<Reviews />)} />
              <Route path="bulk-edit" element={page(<BulkEdit />)} />
              <Route path="combos" element={page(<Combos />)} />
              <Route path="orders" element={page(<Orders />)} />
              <Route path="customers" element={page(<Customers />)} />
              <Route path="customers/:id" element={page(<Customers />)} />
              <Route path="recycle-bin" element={page(<RecycleBin />)} />
              <Route path="coupons" element={page(<Coupons />)} />
              <Route path="admin-info" element={page(<AdminInfo />)} />
              <Route path="contact" element={page(<ContactSubmissions />)} />
              <Route path="conversations" element={page(<Conversations />)} />
              <Route path="gst" element={page(<GstReport />)} />
              <Route path="accounts" element={page(<Accounts />)} />
            </Route>
            <Route path="*" element={<NotFound />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
