export type TabItem = {
  id: string;
  label: string;
  path: string;
};

export type SiteConfig = {
  title: string;
  brand: string;
  docs_url: string;
  tabs: TabItem[];
};

export const fallbackSite: SiteConfig = {
  title: "ORO dashboard",
  brand: "ORO",
  docs_url: "https://oroagents.com/docs",
  tabs: [
    { id: "home", label: "Overview", path: "/" },
    { id: "agents", label: "My Agents", path: "/agents" },
    { id: "overall", label: "Overall", path: "/overall" },
    { id: "auto-sub", label: "Auto-Sub", path: "/auto-sub" },
    { id: "reg", label: "Reg", path: "/reg" },
    { id: "keys", label: "Keys", path: "/keys" },
    { id: "docs", label: "Docs", path: "/docs" },
  ],
};

export type ScoreMode = "psv" | "tf";

export type RaceListItem = {
  race_id: string;
  race_number: number | null;
  status: string | null;
  is_latest: boolean;
  agent_count: number;
  completed_at: string | null;
  overall_agent: string | null;
  overall_score: number | null;
  race_agent: string | null;
  race_score: number | null;
  race_threshold: number | null;
  overall_mid: number | null;
  race_mid: number | null;
  p_mid: number | null;
  s_mid: number | null;
  v_mid: number | null;
  suite_id?: number | null;
  score_mode?: ScoreMode | null;
  tf1_mid?: number | null;
  tf2_mid?: number | null;
  tf3_mid?: number | null;
  tf4_mid?: number | null;
  tf5_mid?: number | null;
  tf6_mid?: number | null;
  tf7_mid?: number | null;
};

export type TrendPoint = {
  race_number: number | null;
  score?: number;
  o_score?: number | null;
  o_mid?: number | null;
  r_score?: number | null;
  r_mid?: number | null;
  anchor?: number | null;
  p_score?: number | null;
  p_mid?: number | null;
  s_score?: number | null;
  s_mid?: number | null;
  v_score?: number | null;
  v_mid?: number | null;
  rank?: number | null;
  o_rank?: number | null;
  r_rank?: number | null;
  p_rank?: number | null;
  s_rank?: number | null;
  v_rank?: number | null;
  tf1_score?: number | null;
  tf1_mid?: number | null;
  tf1_rank?: number | null;
  tf2_score?: number | null;
  tf2_mid?: number | null;
  tf2_rank?: number | null;
  tf3_score?: number | null;
  tf3_mid?: number | null;
  tf3_rank?: number | null;
  tf4_score?: number | null;
  tf4_mid?: number | null;
  tf4_rank?: number | null;
  tf5_score?: number | null;
  tf5_mid?: number | null;
  tf5_rank?: number | null;
  tf6_score?: number | null;
  tf6_mid?: number | null;
  tf6_rank?: number | null;
  tf7_score?: number | null;
  tf7_mid?: number | null;
  tf7_rank?: number | null;
};

export type PsvCell = {
  n: number;
  kind: string;
  score?: number | null;
};

export type SelectedRaceRow = {
  agent_version_id: string;
  rank: number | null;
  agent_name: string;
  version_number: number | null;
  miner_hotkey: string;
  coldkey: string;
  code: "public" | "private";
  lines: number | null;
  overall_score: number | null;
  race_score: number | null;
  margin: number | null;
  qualifying_score: number | null;
  product: number | null;
  shop: number | null;
  voucher: number | null;
  tf1?: number | null;
  tf2?: number | null;
  tf3?: number | null;
  tf4?: number | null;
  tf5?: number | null;
  tf6?: number | null;
  tf7?: number | null;
  product_cells?: PsvCell[];
  shop_cells?: PsvCell[];
  voucher_cells?: PsvCell[];
  submitted_at: string | null;
  races: TrendPoint[];
  race_count: number | null;
  o_trend: TrendPoint[];
  r_trend: TrendPoint[];
  group: string;
  eliminated: boolean;
};

export type SelectedRaceTable = {
  race_id: string;
  race_number: number | null;
  score_mode?: ScoreMode | null;
  total: number;
  rows: SelectedRaceRow[];
};

export async function fetchRaceTable(raceId: string): Promise<SelectedRaceTable | null> {
  try {
    const response = await fetch(`/api/races/${encodeURIComponent(raceId)}/`);
    if (!response.ok) {
      return null;
    }
    const payload = (await response.json()) as SelectedRaceTable;
    const rows = (payload.rows ?? []).map((row) => ({
      ...row,
      eliminated: Boolean(row.eliminated),
      margin: row.margin ?? null,
    }));
    return {
      ...payload,
      rows,
      total: payload.total ?? rows.length,
    };
  } catch {
    return null;
  }
}

export type AgentCodeFile = {
  name: string;
  text: string;
};

export async function fetchAgentCode(versionId: string): Promise<AgentCodeFile[]> {
  try {
    const response = await fetch(`/api/agent-code/${encodeURIComponent(versionId)}/`);
    if (!response.ok) {
      return [];
    }
    const payload = (await response.json()) as { files?: AgentCodeFile[] };
    return payload.files ?? [];
  } catch {
    return [];
  }
}

export type RacesUpdateProgress = {
  updating: boolean;
  race_number: number | null;
  text: string;
};

export async function fetchRacesUpdateProgress(): Promise<RacesUpdateProgress> {
  try {
    const response = await fetch("/api/races/progress/", { cache: "no-store" });
    if (!response.ok) {
      return { updating: false, race_number: null, text: "" };
    }
    const payload = (await response.json()) as Partial<RacesUpdateProgress>;
    return {
      updating: Boolean(payload.updating),
      race_number: payload.race_number ?? null,
      text: payload.text ?? "",
    };
  } catch {
    return { updating: false, race_number: null, text: "" };
  }
}

export async function fetchRacesList(): Promise<RaceListItem[]> {
  try {
    const response = await fetch("/api/races/", {
      cache: "no-store",
      signal: AbortSignal.timeout(20000),
    });
    if (!response.ok) {
      return [];
    }
    const payload = (await response.json()) as { rows?: RaceListItem[] };
    return payload.rows ?? [];
  } catch {
    return [];
  }
}

export async function fetchRacesInfoProgress(): Promise<{
  updating: boolean;
  race_number: number | null;
  text: string;
}> {
  try {
    const response = await fetch("/api/races/info/", { cache: "no-store" });
    if (!response.ok) {
      return { updating: false, race_number: null, text: "" };
    }
    const payload = (await response.json()) as {
      updating?: boolean;
      race_number?: number | null;
      text?: string;
    };
    return {
      updating: Boolean(payload.updating),
      race_number: payload.race_number ?? null,
      text: payload.text ?? "",
    };
  } catch {
    return { updating: false, race_number: null, text: "" };
  }
}

export async function startRacesInfoUpdate(): Promise<boolean> {
  try {
    const response = await fetch("/api/races/", {
      method: "POST",
      cache: "no-store",
      signal: AbortSignal.timeout(15000),
    });
    return response.ok;
  } catch {
    return false;
  }
}

export async function startRaceDatabaseUpdate(raceId: string): Promise<boolean> {
  try {
    const response = await fetch("/api/updatedb/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ race_id: raceId }),
      cache: "no-store",
      signal: AbortSignal.timeout(15000),
    });
    return response.ok;
  } catch {
    return false;
  }
}

export type NetworkStats = {
  netuid: number;
  reg_tao: number | null;
  alpha_tao: number | null;
  tao_usd: number | null;
  source: string;
  updated_at: string | null;
};

export async function fetchTaoUsd(refresh = false): Promise<number | null> {
  try {
    const response = await fetch(refresh ? "/api/tao/?refresh=1" : "/api/tao/", {
      cache: "no-store",
    });
    if (!response.ok) {
      return null;
    }
    const payload = (await response.json()) as { tao_usd?: number | null };
    return payload.tao_usd ?? null;
  } catch {
    return null;
  }
}

export async function fetchNetworkStats(refresh = false): Promise<NetworkStats | null> {
  try {
    const response = await fetch(refresh ? "/api/network/?refresh=1" : "/api/network/", {
      cache: "no-store",
      signal: AbortSignal.timeout(15000),
    });
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as NetworkStats;
  } catch {
    return null;
  }
}

export type RegistrationSpan = "1D" | "1W" | "1M" | "1Y" | "ALL";

export type RegistrationPoint = {
  t: number;
  tao: number;
};

export type RegistrationHistory = {
  netuid: number;
  span: RegistrationSpan;
  current_tao: number | null;
  points: RegistrationPoint[];
  source: string;
  updated_at: string | null;
};

export async function fetchRegistrationHistory(
  span: RegistrationSpan,
): Promise<RegistrationHistory | null> {
  try {
    const response = await fetch(
      `/api/registration/?span=${encodeURIComponent(span)}`,
    );
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as RegistrationHistory;
  } catch {
    return null;
  }
}

export type RegisteredUid = {
  uid: number;
  hotkey: string;
  coldkey: string;
  emission: number;
  registered_at: string | null;
  in_immunity?: boolean;
};

export type RegisteredUids = {
  netuid: number;
  rows: RegisteredUid[];
  to_be_removed: RegisteredUid[];
  source: string;
  updated_at: string | null;
};

export type CurrentOro = {
  suite_id: number | null;
  suite_version: number | null;
  race_number: number | null;
  race_status: string | null;
  qualifying_closes_at: string | null;
  qualifying_threshold: number | null;
  race_threshold: number | null;
  qualifier_count: number | null;
  top_agent_name: string | null;
  top_hotkey: string | null;
  top_score: number | null;
  tao_per_day: number | null;
  usd_per_day: number | null;
  updated_at: string | null;
};

export type RaceStanding = {
  rank: number;
  agent_name: string;
  agent_version_id?: string;
  version_number: number | null;
  miner_hotkey: string;
  coldkey: string;
  qualifying_score: number | null;
  race_score: number | null;
  overall_score: number | null;
  race_margin?: number | null;
  margin: number | null;
  margins: Array<{ race_number: number | null; score: number }>;
  previous: Array<{ race_number: number | null; score: number | null }>;
};

export type FinishedRaceLeaders = {
  race_number: number | null;
  status: string | null;
  overall_agent: string | null;
  overall_score: number | null;
  race_agent: string | null;
  race_score: number | null;
};

export type CurrentRace = {
  race_number: number | null;
  race_status: string | null;
  race_threshold: number | null;
  qualifying_threshold: number | null;
  total: number;
  rows: RaceStanding[];
  updated_at: string | null;
  finished_race?: FinishedRaceLeaders | null;
};

export async function fetchCurrentRace(_refresh = false): Promise<CurrentRace | null> {
  // Overview refresh reloads Mongo-backed /api/race/ only — no ?refresh=1 force rebuild.
  const once = async () => {
    const response = await fetch("/api/race/", {
      cache: "no-store",
      signal: AbortSignal.timeout(20000),
    });
    if (!response.ok) {
      throw new Error(`race ${response.status}`);
    }
    const payload = (await response.json()) as CurrentRace;
    return {
      ...payload,
      rows: payload.rows ?? [],
      total: payload.total ?? 0,
    };
  };
  const wait = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));
  for (let index = 0; index < 2; index += 1) {
    try {
      return await once();
    } catch {
      if (index === 0) {
        await wait(800);
      }
    }
  }
  return null;
}

function singleFlight<T>(slot: { current: Promise<T> | null }, run: () => Promise<T>): Promise<T> {
  if (!slot.current) {
    slot.current = run().finally(() => {
      slot.current = null;
    });
  }
  return slot.current;
}

const currentOroFlight: { current: Promise<CurrentOro | null> | null } = { current: null };

export async function fetchCurrentOro(): Promise<CurrentOro | null> {
  return singleFlight(currentOroFlight, async () => {
    try {
      const response = await fetch("/api/current/");
      if (!response.ok) {
        return null;
      }
      return (await response.json()) as CurrentOro;
    } catch {
      return null;
    }
  });
}

export async function fetchRegisteredUids(_refresh = false): Promise<RegisteredUids | null> {
  try {
    const response = await fetch("/api/neurons/", {
      cache: "no-store",
    });
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as RegisteredUids;
  } catch {
    return null;
  }
}

export type MyAgent = {
  agent_version_id: string;
  agent_name: string;
  version_number: number | null;
  miner_hotkey: string;
  hotkey_name: string;
  coldkey: string;
  uid: number | null;
  deregistered: boolean;
  qualifying_score: number | null;
  race_score: number | null;
  margin: number | null;
  is_active_qualifier: boolean;
  in_current_race: boolean;
  pinned: boolean;
  pinnable: boolean;
  eliminated_in_race_number: number | null;
  status: string | null;
  submitted_at: string | null;
  cooldown_ends_at: string | null;
};

export type MyAgentsPayload = {
  rows: MyAgent[];
  complete?: boolean;
};

const myAgentsFlight: { current: Promise<MyAgentsPayload> | null } = { current: null };

export async function fetchMyAgents(): Promise<MyAgentsPayload> {
  return singleFlight(myAgentsFlight, async () => {
    try {
      const response = await fetch("/api/my-agents/", { cache: "no-store" });
      if (!response.ok) {
        return { rows: [], complete: false };
      }
      const payload = (await response.json()) as { rows?: MyAgent[]; complete?: boolean };
      return { rows: payload.rows ?? [], complete: payload.complete };
    } catch {
      return { rows: [], complete: false };
    }
  });
}

export type AutoSubResult = {
  ok: boolean;
  status: "Success" | "FAIL";
  submitted_at: string | null;
  next_allowed_at: string | null;
  reason: string | null;
};

export async function submitAutoSub(params: {
  hotkey: string;
  agentName: string;
  file: File;
}): Promise<AutoSubResult> {
  const body = new FormData();
  body.append("hotkey", params.hotkey);
  body.append("agent_name", params.agentName);
  body.append("file", params.file, params.file.name);
  try {
    const response = await fetch("/api/auto-sub/submit/", {
      method: "POST",
      body,
    });
    const payload = (await response.json().catch(() => null)) as AutoSubResult | null;
    if (payload && (payload.status === "Success" || payload.status === "FAIL")) {
      return payload;
    }
    return {
      ok: false,
      status: "FAIL",
      submitted_at: new Date().toISOString(),
      next_allowed_at: null,
      reason: "submit-failed",
    };
  } catch {
    return {
      ok: false,
      status: "FAIL",
      submitted_at: new Date().toISOString(),
      next_allowed_at: null,
      reason: "submit-failed",
    };
  }
}

export async function pinAgent(
  agentVersionId: string,
  minerHotkey: string,
): Promise<{ ok: boolean; error?: string }> {
  try {
    const response = await fetch("/api/my-agents/pin/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        agent_version_id: agentVersionId,
        miner_hotkey: minerHotkey,
      }),
    });
    if (response.ok) {
      return { ok: true };
    }
    const payload = (await response.json().catch(() => null)) as { error?: string } | null;
    return { ok: false, error: payload?.error || `pin failed (${response.status})` };
  } catch {
    return { ok: false, error: "pin failed" };
  }
}

export type SavedKeyKind = "cold" | "hot";
export type SavedKeyGroup = "mine" | "other";

export const KEY_COLORS = [
  "#4ea1ff",
  "#3ecf8e",
  "#e89b25",
  "#f5d76e",
  "#e85d75",
  "#b57bff",
  "#2ec4d6",
  "#ff7eb6",
  "#9ad1ff",
  "#7ee081",
  "#ff9f68",
  "#c9a0dc",
] as const;

export function nextKeyColor(used: Iterable<string>): string {
  const taken = new Set(
    [...used].map((item) => item.trim().toLowerCase()).filter(Boolean),
  );
  for (const color of KEY_COLORS) {
    if (!taken.has(color)) {
      return color;
    }
  }
  const hue = (taken.size * 47) % 360;
  const sat = 0.68;
  const light = 0.58;
  const a = sat * Math.min(light, 1 - light);
  const channel = (n: number) => {
    const k = (n + hue / 30) % 12;
    const value = light - a * Math.max(Math.min(k - 3, 9 - k, 1), -1);
    return Math.round(255 * value)
      .toString(16)
      .padStart(2, "0");
  };
  return `#${channel(0)}${channel(8)}${channel(4)}`;
}

export function uniqueKeyColor(preferred: string, used: Iterable<string>): string {
  const color = preferred.trim().toLowerCase();
  const taken = new Set(
    [...used].map((item) => item.trim().toLowerCase()).filter(Boolean),
  );
  if (/^#[0-9a-f]{6}$/.test(color) && !taken.has(color)) {
    return color;
  }
  return nextKeyColor(taken);
}

export type SavedColdKey = {
  id: number;
  ss58: string;
  kind: SavedKeyKind;
  group: SavedKeyGroup;
  nickname: string;
  color: string;
  created_at: string;
  sort: number;
};

export async function fetchColdKeys(): Promise<SavedColdKey[]> {
  try {
    const response = await fetch("/api/keys/");
    if (!response.ok) {
      return [];
    }
    const payload = (await response.json()) as { rows?: SavedColdKey[] };
    return (payload.rows ?? []).map((row) => ({
      ...row,
      kind: row.kind === "hot" ? "hot" : "cold",
      group: row.group === "other" ? "other" : "mine",
      nickname: row.nickname ?? "",
      color: row.color || "#4ea1ff",
      sort: Number.isFinite(row.sort) ? row.sort : 0,
    }));
  } catch {
    return [];
  }
}

export async function createColdKey(
  ss58: string,
  kind: SavedKeyKind = "cold",
  nickname = "",
  group: SavedKeyGroup = "other",
  color = "#4ea1ff",
): Promise<SavedColdKey | null> {
  try {
    const response = await fetch("/api/keys/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ss58, kind, nickname, group, color }),
    });
    if (!response.ok) {
      return null;
    }
    const row = (await response.json()) as SavedColdKey;
    return {
      ...row,
      kind: row.kind === "hot" ? "hot" : "cold",
      group: row.group === "other" ? "other" : "mine",
      nickname: row.nickname ?? "",
      color: row.color || "#4ea1ff",
      sort: Number.isFinite(row.sort) ? row.sort : 0,
    };
  } catch {
    return null;
  }
}

export async function updateColdKey(
  id: number,
  ss58: string,
  kind: SavedKeyKind,
  nickname: string,
  color = "#4ea1ff",
): Promise<SavedColdKey | null> {
  try {
    const response = await fetch(`/api/keys/${id}/`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ss58, kind, nickname, color }),
    });
    if (!response.ok) {
      return null;
    }
    const row = (await response.json()) as SavedColdKey;
    return {
      ...row,
      kind: row.kind === "hot" ? "hot" : "cold",
      group: row.group === "other" ? "other" : "mine",
      nickname: row.nickname ?? "",
      color: row.color || "#4ea1ff",
      sort: Number.isFinite(row.sort) ? row.sort : 0,
    };
  } catch {
    return null;
  }
}

export async function raiseColdKey(id: number): Promise<SavedColdKey | null> {
  try {
    const response = await fetch(`/api/keys/${id}/`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ raise: true }),
    });
    if (!response.ok) {
      return null;
    }
    const row = (await response.json()) as SavedColdKey;
    return {
      ...row,
      kind: row.kind === "hot" ? "hot" : "cold",
      group: row.group === "other" ? "other" : "mine",
      nickname: row.nickname ?? "",
      color: row.color || "#4ea1ff",
      sort: Number.isFinite(row.sort) ? row.sort : 0,
    };
  } catch {
    return null;
  }
}

export async function deleteColdKey(id: number): Promise<boolean> {
  try {
    const response = await fetch(`/api/keys/${id}/`, { method: "DELETE" });
    return response.ok;
  } catch {
    return false;
  }
}

export async function fetchSiteConfig(): Promise<SiteConfig> {
  try {
    const response = await fetch("/api/site/");
    if (!response.ok) {
      return fallbackSite;
    }
    return (await response.json()) as SiteConfig;
  } catch {
    return fallbackSite;
  }
}
