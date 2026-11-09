import { useCallback, useEffect, useState } from "react";

/** Load data on mount; `reload` refetches after a change. */
export function useLoad<T>(load: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const reload = useCallback(() => {
    load().then((value) => { setData(value); setError(""); })
      .catch((e: Error) => setError(e.message));
  }, [load]);
  useEffect(reload, [reload]);
  return { data, error, reload, setError };
}
