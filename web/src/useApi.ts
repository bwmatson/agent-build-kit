import { useEffect, useState } from "react";

import { getJson } from "./api";

export type Loaded<T> = { data: T } | { error: string } | null;

/** The JSON at `path`: null while it loads, then the data or the error that stopped it. */
export function useApi<T>(path: string, reload = 0): Loaded<T> {
  const [result, setResult] = useState<{ path: string; value: Loaded<T> } | null>(null);
  useEffect(() => {
    let current = true;
    getJson<T>(path).then(
      (data) => current && setResult({ path, value: { data } }),
      (error: Error) => current && setResult({ path, value: { error: error.message } }),
    );
    return () => {
      current = false;
    };
  }, [path, reload]);
  return result?.path === path ? result.value : null;
}
