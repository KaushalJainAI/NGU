import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import { cartAPI } from "@/lib/api";
import { useAuth } from "./AuthContext";
import { toast } from "sonner";
import { trackEvent, track } from "@/lib/api/analytics";
import { MAX_ITEM_QUANTITY, MAX_CART_ITEMS, clampQuantity, DEFAULT_TAX_RATE } from "@/config/limits";

interface CartItem {
  id: number;
  variantId?: number | null;
  variantSlug?: string | null;
  weight?: string | null;
  itemType: "product" | "combo";
  name: string;
  image: string;
  price: number;
  originalPrice?: number;
  badge?: string;
  quantity: number;
  stock?: number;
  inStock?: boolean;
  /** GST rate (%) for this line, sourced from the product's tax_rate column.
   *  Falls back to 0 when absent — the backend column is authoritative. */
  taxRate?: number;
}

interface AddToCartResult {
  success: boolean;
  requiresLogin?: boolean;
  error?: string;
}

/**
 * The raw cart-line shape the backend returns (snake_case). Kept explicit so a
 * backend field rename becomes a compile error in `mapBackendToFrontend` instead
 * of silently producing `undefined` prices at checkout.
 */
interface BackendCartItem {
  id: number;
  product_id?: number;
  variant_id?: number | null;
  variant_slug?: string | null;
  weight?: string | null;
  item_type?: "product" | "combo";
  name: string;
  image: string;
  price: number;
  originalPrice?: number;
  quantity: number;
  badge?: string;
  stock?: number;
  in_stock?: boolean;
  tax_rate?: number;
}

/**
 * The API layer throws `APIError` (extends Error) with the backend's message
 * already extracted onto `.message`; network/timeout failures are plain Errors
 * whose message is also user-appropriate. So the message to show the user is
 * simply `error.message` — the old `error?.response?.data?.error` was an axios
 * shape that never exists on our fetch client, so users only ever saw the
 * generic fallback.
 */
const errMsg = (error: unknown, fallback: string): string =>
  error instanceof Error && error.message ? error.message : fallback;

interface CartContextType {
  cart: CartItem[];
  setCart: React.Dispatch<React.SetStateAction<CartItem[]>>;
  addToCart: (item: Omit<CartItem, "quantity"> & { quantity?: number }) => Promise<AddToCartResult>;
  updateQuantity: (id: number, quantity: number, itemType: "product" | "combo", variantId?: number | null) => Promise<void>;
  removeFromCart: (id: number, itemType: "product" | "combo", variantId?: number | null) => Promise<void>;
  clearCart: () => Promise<void>;
  fetchCartFromBackend: () => Promise<void>;
  isLoading: boolean;
}

const CartContext = createContext<CartContextType | undefined>(undefined);

export const useCart = () => {
  const context = useContext(CartContext);
  if (!context) throw new Error("useCart must be within CartProvider");
  return context;
};

const CART_STORAGE_KEY = "shopping_cart";

// Helper function to create unique cart key. For products the line identity
// includes the selected variant, so the same spice in different sizes maps to
// distinct cart lines.
const getCartKey = (
  id: number,
  itemType: "product" | "combo",
  variantId?: number | null
) => `${itemType}-${id}-${variantId ?? ""}`;

export const CartProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isLoggedIn } = useAuth();
  const [cart, setCart] = useState<CartItem[]>(() => {
    const savedCart = localStorage.getItem(CART_STORAGE_KEY);
    return savedCart ? JSON.parse(savedCart) : [];
  });
  const [isLoading, setIsLoading] = useState(false);

  // Save to localStorage on every change
  useEffect(() => {
    localStorage.setItem(CART_STORAGE_KEY, JSON.stringify(cart));
  }, [cart]);

  // Clear cart when user logs out
  useEffect(() => {
    if (!isLoggedIn) {
      setCart([]);
      localStorage.removeItem(CART_STORAGE_KEY);
    }
  }, [isLoggedIn]);

  // Fetch cart from backend when user logs in
  useEffect(() => {
    if (isLoggedIn) {
      fetchCartFromBackend();
    }
  }, [isLoggedIn]);

  // Helper to map backend response to frontend format
  const mapBackendToFrontend = useCallback((items: BackendCartItem[]): CartItem[] => {
    return items.map((item) => ({
      id: Number(item.product_id || item.id),  // Use product_id (the actual product/combo ID)
      variantId: item.variant_id ?? null,
      variantSlug: item.variant_slug ?? null,
      weight: item.weight ?? null,
      itemType: (item.item_type || "product") as "product" | "combo",
      name: item.name,
      image: item.image,
      price: item.price,
      originalPrice: item.originalPrice,
      quantity: item.quantity,
      badge: item.badge,
      stock: item.stock ?? 999,
      inStock: item.in_stock ?? true,
      // An explicit 0 (papad/papad katran) stays 0; only an ABSENT rate falls
      // back to the backend default, so we never under-quote GST in the cart.
      taxRate: item.tax_rate ?? DEFAULT_TAX_RATE,
    }));
  }, []);

  const fetchCartFromBackend = useCallback(async () => {
    if (!isLoggedIn) return;

    try {
      const response = await cartAPI.get();

      if (response.success && response.items && Array.isArray(response.items)) {
        const backendCart = mapBackendToFrontend(response.items);

        setCart(backendCart);
        localStorage.setItem(CART_STORAGE_KEY, JSON.stringify(backendCart));
      }
    } catch (error) {
      console.error("Failed to fetch cart from backend:", error);
      toast.error("Failed to load cart");
    }
  }, [isLoggedIn, mapBackendToFrontend]);

  const addToCart = async (item: Omit<CartItem, "quantity"> & { quantity?: number }): Promise<AddToCartResult> => {
    if (!isLoggedIn) {
      toast.error("Please log in to add items to cart");
      return { success: false, requiresLogin: true };
    }

    // Client-side bounds (backend enforces the same): clamp quantity and block
    // adding a brand-new line once the cart is full. Better UX than a round-trip.
    const quantity = clampQuantity(item.quantity || 1);
    const cartKey = getCartKey(item.id, item.itemType, item.variantId);
    const isNewLine = !cart.some(i => getCartKey(i.id, i.itemType, i.variantId) === cartKey);
    if (isNewLine && cart.length >= MAX_CART_ITEMS) {
      toast.error(`Your cart can hold at most ${MAX_CART_ITEMS} different items.`);
      return { success: false, error: "Cart is full" };
    }

    setIsLoading(true);
    try {
      // Call backend first
      const response = await cartAPI.addItem({
        product_id: item.id,
        item_type: item.itemType,
        quantity,
        variant_id: item.variantId ?? undefined,
      });

      if (response.success && response.items) {
        // Update state from backend response
        const backendCart = mapBackendToFrontend(response.items);
        
        setCart(backendCart);
        track(
          {
            event_type: "add_to_cart",
            [item.itemType === "combo" ? "combo_id" : "product_id"]: item.id,
            metadata: { quantity },
          },
          {
            metric: "add_to_cart",
            product_id: item.itemType === "combo" ? undefined : item.id,
          },
        );
        toast.success("Item added to cart");
        return { success: true };
      } else {
        toast.error(response.error || "Failed to add item");
        return { success: false, error: response.error || "Failed to add item" };
      }
    } catch (error) {
      const errorMsg = errMsg(error, "Failed to add item to cart");
      toast.error(errorMsg);
      return { success: false, error: errorMsg };
    } finally {
      setIsLoading(false);
    }
  };

  /**
   * Shared optimistic-mutation runner for updateQuantity / removeFromCart /
   * clearCart. Snapshots the cart, applies `optimistic` immediately, then runs
   * `apiCall`; on success it re-syncs from the backend response (via
   * `onSuccess`), and on ANY failure (`success:false` OR a thrown APIError) it
   * reverts to the snapshot and shows `failMsg`. This is the single source of
   * truth for the "optimistic update + revert on error" pattern the three
   * mutations used to each re-implement.
   */
  const mutateCart = async (
    optimistic: (prev: CartItem[]) => CartItem[],
    apiCall: () => Promise<{ success?: boolean; items?: unknown[]; error?: string }>,
    failMsg: string,
    onSuccess?: (response: { items?: unknown[] }) => void,
  ) => {
    const previousCart = [...cart];
    setCart(optimistic);
    setIsLoading(true);
    try {
      const response = await apiCall();
      if (response.success === false) {
        setCart(previousCart);
        toast.error(response.error || failMsg);
        return;
      }
      onSuccess?.(response);
    } catch (error) {
      setCart(previousCart);
      toast.error(errMsg(error, failMsg));
    } finally {
      setIsLoading(false);
    }
  };

  const updateQuantity = async (id: number, quantity: number, itemType: "product" | "combo", variantId?: number | null) => {
    if (!isLoggedIn) {
      toast.error("Please log in to update cart");
      return;
    }

    if (quantity <= 0) {
      await removeFromCart(id, itemType, variantId);
      return;
    }

    if (quantity > MAX_ITEM_QUANTITY) {
      toast.error(`Quantity cannot exceed ${MAX_ITEM_QUANTITY} per item.`);
      return;
    }

    const cartKey = getCartKey(id, itemType, variantId);
    await mutateCart(
      prev => prev.map(i => (getCartKey(i.id, i.itemType, i.variantId) === cartKey ? { ...i, quantity } : i)),
      () => cartAPI.updateItem({ product_id: id, item_type: itemType, quantity, variant_id: variantId ?? undefined }),
      "Failed to update quantity",
      response => { if (response.items) setCart(mapBackendToFrontend(response.items as BackendCartItem[])); },
    );
  };

  const removeFromCart = async (id: number, itemType: "product" | "combo", variantId?: number | null) => {
    if (!isLoggedIn) {
      toast.error("Please log in to remove items");
      return;
    }

    const cartKey = getCartKey(id, itemType, variantId);
    await mutateCart(
      prev => prev.filter(i => getCartKey(i.id, i.itemType, i.variantId) !== cartKey),
      () => cartAPI.removeItem({ product_id: id, item_type: itemType, variant_id: variantId ?? undefined }),
      "Failed to remove item",
      response => {
        if (response.items) setCart(mapBackendToFrontend(response.items as BackendCartItem[]));
        trackEvent({
          event_type: "remove_from_cart",
          [itemType === "combo" ? "combo_id" : "product_id"]: id,
        });
      },
    );
  };

  const clearCart = async () => {
    if (!isLoggedIn) {
      toast.error("Please log in to clear cart");
      return;
    }

    await mutateCart(
      () => [],
      () => cartAPI.clear(),
      "Failed to clear cart",
      () => localStorage.removeItem(CART_STORAGE_KEY),
    );
  };

  return (
    <CartContext.Provider 
      value={{ 
        cart, 
        setCart, 
        addToCart, 
        updateQuantity, 
        removeFromCart, 
        clearCart, 
        fetchCartFromBackend,
        isLoading 
      }}
    >
      {children}
    </CartContext.Provider>
  );
};
