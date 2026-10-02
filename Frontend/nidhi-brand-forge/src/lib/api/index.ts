// Re-export all API modules
export * from "./config";
export * from "./auth";
export * from "./products";
export * from "./categories";
export * from "./combos";
export * from "./cart";
export * from "./orders";
export * from "./coupons";
export * from "./favorites";
export * from "./reviews";
export * from "./payments";
export * from "./search";
export * from "./geo";

// Legacy exports for backwards compatibility
export { authAPI as userAPI } from "./auth";
