import type { MyAgent } from "./api";

function submitErrorLabel(value: string): string | null {
  const first = value.split("\n")[0].trim().toLowerCase();
  if (!first || /eliminated|qualifying|eligible|queued|running|received|cancelled/.test(first)) {
    return null;
  }
  if (/anti-cheating|too-large|invalid-file|similarity|code-analysis/.test(first)) {
    return first;
  }
  if (/^[a-z0-9]+(?:-[a-z0-9]+)+$/.test(first)) {
    return first;
  }
  return null;
}

function formatStatus(
  value: string,
  qualifyingScore: number | null = null,
  threshold: number | null = null,
  raceNumber: number | null = null,
  eliminatedRace: number | null = null,
  selectedForRace: boolean = false,
): string {
  const cleaned = (value || "").replace(/[()]/g, "").replace(/\r/g, "").trim();
  const raceMatch = cleaned.match(/#\s*(\d+)/);
  const race =
    raceNumber != null ? String(raceNumber) : raceMatch?.[1] ?? null;
  const queueLabel = (pinned: boolean) =>
    pinned
      ? race
        ? `Qualifying In\nRace #${race}`
        : "Qualifying In"
      : "Queued";
  if (/^(running|received)$/i.test(cleaned.split("\n")[0])) {
    return cleaned.split("\n")[0];
  }
  if (selectedForRace && !submitErrorLabel(cleaned) && !/eliminated/i.test(cleaned)) {
    return queueLabel(true);
  }
  if (qualifyingScore != null && threshold != null) {
    const score = qualifyingScore <= 1 && threshold > 1 ? qualifyingScore * 100 : qualifyingScore;
    const cut = threshold <= 1 && qualifyingScore > 1 ? threshold * 100 : threshold;
    if (score < cut && !/eliminated/i.test(cleaned) && !submitErrorLabel(cleaned)) {
      return "Dropped";
    }
  }
  if (!cleaned) {
    if (qualifyingScore != null && threshold != null) {
      const score = qualifyingScore <= 1 && threshold > 1 ? qualifyingScore * 100 : qualifyingScore;
      const cut = threshold <= 1 && qualifyingScore > 1 ? threshold * 100 : threshold;
      if (score < cut) {
        return "Dropped";
      }
    }
    if (qualifyingScore != null || race) {
      return queueLabel(false);
    }
    return "Dropped";
  }
  const submitError = submitErrorLabel(cleaned);
  if (submitError) {
    return race ? `${submitError}\nRace #${race}` : submitError;
  }
  if (/eliminated/i.test(cleaned)) {
    const number = raceMatch?.[1] ?? (eliminatedRace != null ? String(eliminatedRace) : null);
    return number ? `Eliminated\nRace #${number}` : "Eliminated";
  }
  if (/^dropped$/i.test(cleaned.split("\n")[0]) || /qualifying drop/i.test(cleaned)) {
    return "Dropped";
  }
  if (/^(queued|running|received)$/i.test(cleaned.split("\n")[0]) && !/race\s*#/i.test(cleaned) && qualifyingScore == null) {
    return cleaned.split("\n")[0];
  }
  if (qualifyingScore != null && threshold != null) {
    const score = qualifyingScore <= 1 && threshold > 1 ? qualifyingScore * 100 : qualifyingScore;
    const cut = threshold <= 1 && qualifyingScore > 1 ? threshold * 100 : threshold;
    if (score < cut) {
      return "Dropped";
    }
  }
  const inQualifying =
    /qualifying|eligible/i.test(cleaned) ||
    (/queued/i.test(cleaned) && /race\s*#/i.test(cleaned)) ||
    qualifyingScore != null;
  const qualifyingRace = raceNumber != null ? String(raceNumber) : race;
  if (inQualifying && qualifyingRace) {
    return selectedForRace ? `Qualifying In\nRace #${qualifyingRace}` : "Queued";
  }
  return cleaned;
}

function rowStatus(
  row: MyAgent,
  threshold: number | null,
  raceNumber: number | null,
): string {
  return formatStatus(
    row.status,
    row.qualifying_score,
    threshold,
    raceNumber,
    row.eliminated_in_race_number,
    row.pinned || row.in_current_race,
  );
}

function isAvailableAgentStatus(value: string): boolean {
  const state = value.replace(/[_-]/g, " ").toLowerCase();
  const first = state.split("\n")[0] || "";
  if (first.includes("drop")) {
    return false;
  }
  return state.includes("queued") || state.includes("qualifying");
}

export function availableAgentCount(
  rows: MyAgent[],
  threshold: number | null,
  raceNumber: number | null,
): number {
  const seen = new Set<string>();
  for (const row of rows) {
    const name = (row.agent_name || "").trim();
    const key = row.agent_version_id || `${name}:${row.version_number ?? ""}`;
    if (
      !name ||
      !key ||
      seen.has(key) ||
      !(
        isAvailableAgentStatus(rowStatus(row, threshold, raceNumber)) ||
        isAvailableAgentStatus(row.status || "")
      )
    ) {
      continue;
    }
    seen.add(key);
  }
  return seen.size;
}

function cooldownReady(endsAt: string | null, now: number): boolean {
  if (!endsAt) {
    return true;
  }
  const text = endsAt.trim();
  const stamp = /[zZ]|[+-]\d{2}:\d{2}$/.test(text)
    ? Date.parse(text)
    : Date.parse(`${text.includes("T") ? text : text.replace(" ", "T")}Z`);
  const left = Math.floor((stamp - now) / 1000);
  return !Number.isFinite(left) || left <= 0;
}

export function availableHotkeyCounts(
  rows: MyAgent[],
  now: number,
): { ready: number; total: number } {
  const seen = new Set<string>();
  let ready = 0;
  let total = 0;
  for (const row of rows) {
    const key = row.miner_hotkey || row.hotkey_name || "";
    if (!key || seen.has(key) || row.deregistered) {
      continue;
    }
    seen.add(key);
    total += 1;
    if (cooldownReady(row.cooldown_ends_at, now)) {
      ready += 1;
    }
  }
  return { ready, total };
}
