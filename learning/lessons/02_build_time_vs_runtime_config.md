# 02 — Build-Time vs Runtime Config (the ₹1 Bug)

> Source: `Frontend/nidhi-brand-forge/src/config/runtimeEnv.ts`,
> `Frontend/nidhi-brand-forge/src/config/limits.ts`,
> `Frontend/nidhi-brand-forge/docker-entrypoint.d/40-runtime-config.sh`,
> `Backend/spices_backend/limits.py`, `docker-compose.prod.yml`
> Fixed: 2026-08-05 (free delivery), 2026-07-20 (admin API URL)

---

## The symptom

A customer filled a cart to exactly **₹499**. The cart page said **"free
delivery"**. At checkout they were charged **₹69.62** for delivery.

The rule is "delivery is free from ₹499". One part of the system thought the
number was 499. Another thought it was 500.

---

## Why it happened

The number lived in three places:

| Place | Value | How it got there |
|---|---|---|
| Storefront image | **499** | Compiled into the JavaScript when the image was built |
| Backend environment on the server | **500** | A line in the env file |
| Storefront container environment | *empty* | The compose file passes `FREE_SHIPPING_THRESHOLD=${FREE_SHIPPING_THRESHOLD:-}` |

To see why this matters you need one fact about frontends.

### A browser app has no environment variables

A Python server reads its settings when it starts. Change the env file, restart
the container, and the new value is used.

A React app is different. It is built once into plain files. The build tool
(Vite) finds every `import.meta.env.VITE_SOMETHING` and **replaces it with the
value at build time**. After that the number is part of the JavaScript, like any
other constant. The browser that runs it has no env file to read.

So "change the env and restart" does nothing for a value baked into the
frontend. You would have to build a new image.

### The runtime bridge, and its gap

This project adds a way around that. When the storefront container starts, a
script writes a small file from the container's environment:

```sh
cat > /usr/share/nginx/html/config.js <<EOF
window.APP_CONFIG = {
  API_URL: "${API_URL:-/api}",
  FREE_SHIPPING_THRESHOLD: "${FREE_SHIPPING_THRESHOLD:-}",
  ...
};
EOF
```

And the app reads it first:

```ts
export function readEnv(viteName: string): string | undefined {
  const r = runtime?.[key];
  if (r != null && r !== "") return r;        // a runtime value wins…
  const b = import.meta.env[viteName];        // …otherwise the baked value
  return b != null && b !== "" ? b : undefined;
}
```

Read the second line carefully. **An empty runtime value falls back to the
baked one.** The container was given an empty value. So the storefront used the
499 baked into the image, while the backend used the 500 from its env file. The
runtime bridge existed and could not help, because nothing was passed through
it.

The backend is the one that charges, so the customer saw one thing and paid
another.

---

## The fix

499 was the intended number. It was set in:

- the backend code default and the storefront code default,
- every env file in the project,
- the production env file, followed by recreating the backend and scheduler
  containers.

And one rule was written down: **the storefront default is baked in.** To
change this number you must rebuild the storefront image, or set it in the
storefront container's environment so the start script writes it. Changing only
the backend's env file re-opens exactly this bug.

---

## The same idea, a second time: the admin panel's API address

The admin panel image used to default to an **absolute** API address,
`https://nidhimasala.com/api`. Later that domain's DNS stopped pointing at the
server. The panel, loaded from the other domain, kept calling the dead one and
simply stopped working.

Rebuilding the image with a different address did **not** fix it, because the
container's generated `config.js` overrides the baked value. The value that
mattered was the container's environment.

The fix was to make the address **relative**: `/api`. A relative address means
"the same domain this page came from". It works on every domain, and the login
cookie is sent because the request is same-origin.

So the two bugs are mirror images:

| Bug | What was wrong | Which layer won |
|---|---|---|
| Free delivery | Runtime value empty | The baked value |
| Admin API address | Runtime value set, and wrong | The runtime value |

In both, someone changed one layer and the other one decided the result.

---

## The general lesson

> **A value that two programs must agree on needs one owner.** Either one
> program asks the other for it, or both are built from the same source.

For a number like the free-delivery limit, the cleanest design is for the
storefront to get it from the backend (an API response) and not carry its own
copy. Then they cannot disagree. This project keeps two copies, so the rule
above has to be remembered by people. That is the weaker design, and it is
worth saying so in an interview.

And know, for every setting, **when it is read**:

| Read at | Changing it needs |
|---|---|
| Build time (baked into the bundle) | A new image |
| Container start (written to `config.js`) | Recreating the container |
| Process start (Django settings) | Restarting the process |
| Every request (a database row) | Nothing |

---

## Interview questions

1. *Why can't a React app read environment variables in production?*
   → It runs in the user's browser. The build tool replaces them with their
   values while building. After that they are constants in the file.

2. *How do you configure one frontend image for several deployments?*
   → Generate a small config file when the container starts and load it before
   the app. Read that first, fall back to the baked value.

3. *The frontend and backend show different prices. Where do you look?*
   → List every place the number is defined and when each is read. One of them
   is stale. Then ask why there are two copies at all.

4. *Why use a relative API URL?*
   → It calls whatever domain served the page. That keeps requests same-origin
   so cookies are sent, and one image works on every domain.

5. *What is the weakness of "fall back to the default when the value is
   empty"?*
   → A missing value and a wrong value look the same from outside. Log which
   source each setting came from at start-up. This project's start script
   prints `<baked>` for exactly that reason.
