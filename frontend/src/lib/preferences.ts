import { Dispatch, SetStateAction, useEffect, useState } from "react";

/** Versioned browser preferences; browsing still works if storage is unavailable. */
export function useStoredPreferences<T>(key: string, defaults: T, validate: (value: unknown) => T):
  [T, Dispatch<SetStateAction<T>>, boolean] {
  const [initial] = useState(() => {
    try {
      const raw = localStorage.getItem(key);
      return { value: raw ? validate(JSON.parse(raw)) : defaults, unavailable: false };
    } catch (error) {
      return { value: defaults, unavailable: !(error instanceof SyntaxError) };
    }
  });
  const [value, setValue] = useState(initial.value);
  const [unavailable, setUnavailable] = useState(initial.unavailable);
  useEffect(() => {
    try { localStorage.setItem(key, JSON.stringify(value)); }
    catch { setUnavailable(true); }
  }, [key, value]);
  return [value, setValue, unavailable];
}
