import type { MyAgent } from "./api";

const STORAGE_KEY = "oro-hotkey-cooldowns";
const EVENT_NAME = "oro-hotkey-cooldown";

function laterIso(left: string | null | undefined, right: string | null | undefined): string | null {
  const leftStamp = left ? Date.parse(left) : Number.NaN;
  const rightStamp = right ? Date.parse(right) : Number.NaN;
  if (Number.isFinite(leftStamp) && Number.isFinite(rightStamp)) {
    return leftStamp >= rightStamp ? left : right;
  }
  if (Number.isFinite(leftStamp)) {
    return left ?? null;
  }
  if (Number.isFinite(rightStamp)) {
    return right ?? null;
  }
  return null;
}

function readStored(): Record<string, string> {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

export function rememberHotkeyCooldown(hotkey: string, endsAt: string | null): void {
  if (!hotkey || !endsAt) {
    return;
  }
  const all = readStored();
  const next = laterIso(all[hotkey], endsAt);
  if (!next) {
    return;
  }
  all[hotkey] = next;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(all));
  } catch {
    /* ignore quota */
  }
  window.dispatchEvent(new CustomEvent(EVENT_NAME, { detail: { hotkey, endsAt: next } }));
}

export function applyHotkeyCooldowns(rows: MyAgent[]): MyAgent[] {
  const stored = readStored();
  if (!Object.keys(stored).length) {
    return rows;
  }
  return rows.map((row) => {
    const ends = laterIso(row.cooldown_ends_at, stored[row.miner_hotkey || ""]);
    return ends && ends !== row.cooldown_ends_at ? { ...row, cooldown_ends_at: ends } : row;
  });
}

export function subscribeHotkeyCooldowns(
  onChange: (hotkey: string, endsAt: string) => void,
): () => void {
  const handle = (event: Event) => {
    const detail = (event as CustomEvent<{ hotkey?: string; endsAt?: string }>).detail;
    if (detail?.hotkey && detail.endsAt) {
      onChange(detail.hotkey, detail.endsAt);
    }
  };
  const storage = (event: StorageEvent) => {
    if (event.key !== STORAGE_KEY || !event.newValue) {
      return;
    }
    try {
      const parsed = JSON.parse(event.newValue) as Record<string, string>;
      for (const [hotkey, endsAt] of Object.entries(parsed)) {
        if (hotkey && endsAt) {
          onChange(hotkey, endsAt);
        }
      }
    } catch {
      /* ignore */
    }
  };
  window.addEventListener(EVENT_NAME, handle);
  window.addEventListener("storage", storage);
  return () => {
    window.removeEventListener(EVENT_NAME, handle);
    window.removeEventListener("storage", storage);
  };
}
