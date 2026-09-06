/**
 * Query parameter serialization (spec section 15).
 *
 * One function turns a typed filter object into something Axios can send. It
 * exists so the rules below are applied identically at every call site rather
 * than remembered at each one.
 *
 * **Nothing is ever concatenated into a URL.** The result is handed to Axios as
 * `params`, which encodes each value. There is no string building here, and no
 * opportunity for a value to change the shape of a request.
 *
 * WHY UNDEFINED AND EMPTY STRINGS ARE DROPPED
 *
 * An absent filter and an explicitly empty one must produce the same request.
 * If they did not, clearing a text input would send `?machine_id=` and the
 * backend would reject it as a malformed UUID -- a validation error caused
 * entirely by the frontend, for a filter the user just removed.
 *
 * Dropping them also keeps the URL, and therefore the TanStack Query key,
 * stable: `{page: 1}` and `{page: 1, machine_id: undefined}` are the same query
 * and must not produce two cache entries.
 *
 * WHY `null` IS KEPT
 *
 * `undefined` means "no opinion". `null` would mean "explicitly nothing", which
 * no endpoint currently accepts -- but conflating the two would silently
 * discard a deliberate choice if one ever did.
 */
import type { IsoDate } from "@/types/common";

/**
 * Values a query parameter may hold.
 *
 * Deliberately narrow. A filter object typed against this cannot carry a nested
 * object or a function, so nothing unserialisable reaches Axios, and no caller
 * can smuggle an arbitrary expression through a filter (spec section 15).
 */
export type QueryParamValue =
  string | number | boolean | Date | null | undefined | readonly (string | number)[];

/**
 * A typed filter object, as accepted by the API modules.
 *
 * The helpers below are generic over `object` rather than requiring this exact
 * type. A TypeScript `interface` has no implicit index signature, so
 * `ProductionFilters` is not assignable to `Record<string, QueryParamValue>` --
 * and declaring every filter as a type alias with an index signature would let
 * any key through, which is the opposite of what spec section 15 asks for.
 *
 * So the constraint stays at the call sites, where filters are declared as
 * closed interfaces, and the serializer narrows each value at runtime. A value
 * it does not recognise is dropped rather than coerced, so an accidentally
 * nested object cannot arrive at the API as the string "[object Object]".
 */
export type QueryParams = Record<string, QueryParamValue>;

/** What Axios receives: only values it can encode without ambiguity. */
export type SerializedParams = Record<string, string | number | boolean | (string | number)[]>;

/**
 * Render a `Date` as the `YYYY-MM-DD` the API expects.
 *
 * `toISOString` is used rather than any locale-aware formatter: it is always
 * UTC. `toLocaleDateString` would produce a different date either side of
 * midnight depending on the viewer's timezone, so a user in Auckland and one in
 * Los Angeles would silently query different days.
 */
export function toIsoDate(value: Date): IsoDate {
  return value.toISOString().slice(0, 10);
}

/**
 * Convert a typed filter object into Axios `params`.
 *
 * Drops `undefined` and empty strings; keeps `false` and `0`, which are
 * meaningful values rather than absent ones -- `?upcoming_only=false` and
 * omitting it entirely can mean different things, and `page=0` should reach the
 * backend and be rejected rather than silently becoming page 1.
 */
export function buildParams<TFilters extends object>(
  filters: TFilters | undefined,
): SerializedParams {
  if (!filters) {
    return {};
  }

  const params: SerializedParams = {};

  for (const [key, value] of Object.entries(filters) as [string, unknown][]) {
    if (value === undefined || value === null) {
      continue;
    }

    if (typeof value === "string") {
      const trimmed = value.trim();
      // An empty string is an absent filter, not a filter for emptiness.
      if (trimmed === "") {
        continue;
      }
      params[key] = trimmed;
      continue;
    }

    if (value instanceof Date) {
      params[key] = toIsoDate(value);
      continue;
    }

    if (Array.isArray(value)) {
      // Serialized by the client as repeated keys (`?shift=A&shift=B`), which
      // is what FastAPI expects for a list query parameter. An empty array is
      // no filter at all.
      const items = value.filter(
        (item): item is string | number =>
          (typeof item === "string" && item !== "") || typeof item === "number",
      );
      if (items.length > 0) {
        params[key] = items;
      }
      continue;
    }

    if (typeof value === "number") {
      // NaN would serialise as the literal "NaN" and produce a confusing 422.
      // Almost always an arithmetic slip upstream, so it is dropped here.
      if (Number.isNaN(value)) {
        continue;
      }
      params[key] = value;
      continue;
    }

    if (typeof value === "boolean") {
      // `false` is kept deliberately: omitting a filter and setting it false
      // can mean different things to an endpoint.
      params[key] = value;
      continue;
    }

    // Anything else -- a nested object, a function, a symbol -- is not a query
    // parameter. Dropped rather than coerced, so a mistake upstream produces a
    // missing filter rather than a nonsense one the backend has to reject.
  }

  return params;
}

/**
 * A stable representation of a filter set, for use in a TanStack Query key.
 *
 * The same normalisation as `buildParams`, then sorted by key. Sorting matters:
 * `{a: 1, b: 2}` and `{b: 2, a: 1}` describe one query and must produce one
 * cache entry, and object key order is insertion order in JavaScript.
 */
export function normalizeFilters<TFilters extends object>(
  filters: TFilters | undefined,
): SerializedParams {
  const params = buildParams(filters);
  const sorted: SerializedParams = {};
  for (const key of Object.keys(params).sort()) {
    sorted[key] = params[key];
  }
  return sorted;
}
