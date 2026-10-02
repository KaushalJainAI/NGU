/**
 * Make React resilient to Google Translate (and similar DOM-rewriting tools).
 *
 * Google Translate replaces text nodes in place. React keeps its own
 * references to the original nodes, so when it later unmounts a subtree it can
 * call removeChild / insertBefore on a node Translate has already moved or
 * swapped. The DOM then throws
 *   "Failed to execute 'removeChild' on 'Node': The node to be removed is not
 *    a child of this node"
 * which crashes the entire React tree (most visibly on Radix Portals such as
 * Select / Dialog dropdowns).
 *
 * The well-known fix (facebook/react#11538) is to guard these two Node methods
 * so an invalid call becomes a safe no-op instead of a throw. We only short-
 * circuit the exact mismatching case; valid operations run unchanged.
 *
 * Must run once, before React renders.
 */
export function installGoogleTranslateReactFix() {
  if (typeof Node !== "function" || !Node.prototype) return;
  const w = window as unknown as { __gtReactFixInstalled?: boolean };
  if (w.__gtReactFixInstalled) return;
  w.__gtReactFixInstalled = true;

  const originalRemoveChild = Node.prototype.removeChild;
  Node.prototype.removeChild = function <T extends Node>(this: Node, child: T): T {
    if (child.parentNode !== this) {
      if (process.env.NODE_ENV !== "production") {
        // eslint-disable-next-line no-console
        console.warn("Suppressed removeChild on a node with a different parent (Google Translate).", child);
      }
      return child;
    }
    return originalRemoveChild.call(this, child) as T;
  };

  const originalInsertBefore = Node.prototype.insertBefore;
  Node.prototype.insertBefore = function <T extends Node>(
    this: Node,
    newNode: T,
    referenceNode: Node | null
  ): T {
    if (referenceNode && referenceNode.parentNode !== this) {
      if (process.env.NODE_ENV !== "production") {
        // eslint-disable-next-line no-console
        console.warn("Suppressed insertBefore with a reference node from a different parent (Google Translate).", referenceNode);
      }
      return newNode;
    }
    return originalInsertBefore.call(this, newNode, referenceNode) as T;
  };
}
