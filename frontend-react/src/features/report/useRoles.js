import { useEffect, useState } from "react";
import { apiGet } from "../../lib/api";

/**
 * The roles /score/standalone accepts as `target_role`.
 *
 * Fetched rather than hard-coded so the picker can't drift out of sync
 * with the ontology the backend actually scores against -- a stale
 * option here would look identical to a working one until the request
 * came back 400.
 *
 * Failure is deliberately not surfaced as an error. This is an optional
 * refinement to a report that works without it: if the list can't be
 * loaded the picker simply doesn't render, and the backend infers the
 * role exactly as it did before. Blocking the whole analysis because a
 * dropdown wouldn't populate would be a worse trade.
 */
export function useRoles() {
  const [roles, setRoles] = useState([]);

  useEffect(() => {
    let cancelled = false;
    apiGet("/score/roles")
      .then((data) => {
        if (!cancelled) setRoles(data.roles || []);
      })
      .catch(() => {
        if (!cancelled) setRoles([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return roles;
}
