import { useSyncExternalStore } from "react";

import {
  createColdKey,
  deleteColdKey,
  fetchColdKeys,
  nextKeyColor,
  raiseColdKey,
  updateColdKey,
  type SavedKeyGroup,
  type SavedKeyKind,
} from "./api";

const LOCAL_STORAGE = "oro-my-ss58";

type Snapshot = {
  keys: string[];
  otherKeys: string[];
  rows: Array<{
    id: number;
    ss58: string;
    kind: SavedKeyKind;
    group: SavedKeyGroup;
    nickname: string;
    color: string;
    created_at: string;
    sort: number;
  }>;
};

let rows: Snapshot["rows"] = [];
let snapshot: Snapshot = { keys: [], otherKeys: [], rows };
let inflight: Promise<void> | null = null;
const listeners = new Set<() => void>();

function emit() {
  snapshot = {
    keys: rows
      .filter(
        (row) =>
          row.group === "mine" || row.nickname.trim().toLowerCase() === "po",
      )
      .map((row) => row.ss58),
    otherKeys: rows.filter((row) => row.group === "other").map((row) => row.ss58),
    rows,
  };
  for (const listener of listeners) {
    listener();
  }
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function getSnapshot(): Snapshot {
  return snapshot;
}

function localKeys(): string[] {
  try {
    const raw = window.localStorage.getItem(LOCAL_STORAGE);
    const parsed = raw ? (JSON.parse(raw) as unknown) : [];
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed.filter((item): item is string => typeof item === "string" && item.length > 0);
  } catch {
    return [];
  }
}

async function refresh() {
  if (inflight) {
    return inflight;
  }
  inflight = (async () => {
    rows = await fetchColdKeys();
    const pending = localKeys().filter((key) => !rows.some((row) => row.ss58 === key));
    for (const key of pending) {
      const created = await createColdKey(
        key,
        "cold",
        "",
        "other",
        nextKeyColor(rows.map((row) => row.color)),
      );
      if (created) {
        rows = [created, ...rows.filter((row) => row.id !== created.id)];
      }
    }
    if (pending.length) {
      try {
        window.localStorage.removeItem(LOCAL_STORAGE);
      } catch {
        /* ignore */
      }
      rows = await fetchColdKeys();
    }
    emit();
  })().finally(() => {
    inflight = null;
  });
  return inflight;
}

void refresh();

export function reloadKeys() {
  return refresh();
}

export function useMyMiners() {
  const current = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  const keySet = new Set(current.keys);
  const otherSet = new Set(current.otherKeys);

  const matchSet = (set: Set<string>, hotkey: string, coldkey: string) =>
    Boolean((coldkey && set.has(coldkey)) || (hotkey && set.has(hotkey)));

  const isMine = (hotkey: string, coldkey: string) => matchSet(keySet, hotkey, coldkey);
  const isOther = (hotkey: string, coldkey: string) => matchSet(otherSet, hotkey, coldkey);
  const otherNicknames = [
    "Po",
    ...new Set(
      current.rows
        .filter((row) => row.group === "other" && row.nickname.trim())
        .map((row) => row.nickname.trim())
        .filter((name) => name.toLowerCase() !== "po"),
    ),
  ];
  const isOtherNickname = (nickname: string, hotkey: string, coldkey: string) => {
    if (!nickname) {
      return false;
    }
    if (nickname.trim().toLowerCase() === "po") {
      return isMine(hotkey, coldkey);
    }
    const set = new Set(
      current.rows
        .filter((row) => row.group === "other" && row.nickname.trim() === nickname)
        .map((row) => row.ss58),
    );
    return matchSet(set, hotkey, coldkey);
  };

  const addKey = async (
    value: string,
    kind: SavedKeyKind = "cold",
    nickname = "",
    group: SavedKeyGroup = "other",
    color = "#4ea1ff",
  ) => {
    const key = value.trim();
    if (!key || rows.some((row) => row.ss58 === key)) {
      return false;
    }
    const created = await createColdKey(key, kind, nickname.trim(), group, color);
    if (!created) {
      return false;
    }
    await refresh();
    return true;
  };

  const removeKey = async (value: string) => {
    const row = rows.find((item) => item.ss58 === value);
    if (row) {
      await deleteColdKey(row.id);
    }
    await refresh();
  };

  const removeRow = async (id: number) => {
    await deleteColdKey(id);
    await refresh();
  };

  const editKey = async (
    id: number,
    value: string,
    kind: SavedKeyKind,
    nickname = "",
    color = "#4ea1ff",
  ) => {
    const key = value.trim();
    if (!key || rows.some((row) => row.ss58 === key && row.id !== id)) {
      return false;
    }
    const updated = await updateColdKey(id, key, kind, nickname.trim(), color);
    if (!updated) {
      return false;
    }
    await refresh();
    return true;
  };

  const raiseKey = async (id: number) => {
    const updated = await raiseColdKey(id);
    if (!updated) {
      return false;
    }
    await refresh();
    return true;
  };

  return {
    keys: current.keys,
    rows: current.rows,
    isMine,
    isOther,
    isOtherNickname,
    otherNicknames,
    addKey,
    editKey,
    raiseKey,
    removeKey,
    removeRow,
  };
}
