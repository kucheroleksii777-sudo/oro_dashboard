import { useEffect, useMemo, useRef, useState } from "react";
import Check from "@mui/icons-material/Check";
import Close from "@mui/icons-material/Close";
import Groups from "@mui/icons-material/Groups";
import KeyboardArrowDown from "@mui/icons-material/KeyboardArrowDown";
import Search from "@mui/icons-material/Search";
import Box from "@mui/material/Box";
import CircularProgress from "@mui/material/CircularProgress";
import IconButton from "@mui/material/IconButton";
import InputAdornment from "@mui/material/InputAdornment";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import {
  fetchRaceTable,
  fetchRacesInfoProgress,
  fetchRacesList,
  fetchRacesUpdateProgress,
  startRaceDatabaseUpdate,
  startRacesInfoUpdate,
  type RaceListItem,
  type ScoreMode,
  type SelectedRaceRow,
} from "../api";
import { useMyMiners } from "../myKeys";
import SelectedRaceTable from "./SelectedRaceTable";

const ORANGE = "#e89b25";
const MUTED = "#8a8f98";
const NO_GROUP = "No Group";
const LIVE_STATUS = new Set([
  "RACE_RUNNING",
  "QUALIFYING",
  "QUALIFYING_OPEN",
  "RUNNING",
  "IN_PROGRESS",
]);
const mono =
  'ui-monospace, "SFMono-Regular", "Cascadia Mono", "Roboto Mono", Menlo, Consolas, monospace';

function finishedRaces(rows: RaceListItem[]): RaceListItem[] {
  return rows.filter((row) => !LIVE_STATUS.has((row.status || "").toUpperCase()));
}

function keyGroupLabel(row: { nickname: string; group: string }): string {
  const nick = row.nickname.trim();
  if (nick) {
    return nick;
  }
  return row.group === "mine" ? "Po" : row.group;
}

type KeyGroup = {
  label: string;
  color: string;
  ss58s: Set<string>;
};

type SortKey =
  | "race"
  | "overall"
  | "qualifying"
  | "product"
  | "shop"
  | "voucher"
  | "ps"
  | "pv"
  | "sv"
  | "tf1"
  | "tf2"
  | "tf3"
  | "tf4"
  | "tf5"
  | "tf6"
  | "tf7";

const PSV_SORT: Array<{ id: SortKey; label: string }> = [
  { id: "product", label: "Product" },
  { id: "shop", label: "Shop" },
  { id: "voucher", label: "Voucher" },
  { id: "ps", label: "P+S" },
  { id: "pv", label: "P+V" },
  { id: "sv", label: "S+V" },
];

const TF_SORT: Array<{ id: SortKey; label: string }> = [
  { id: "tf1", label: "TF1" },
  { id: "tf2", label: "TF2" },
  { id: "tf3", label: "TF3" },
  { id: "tf4", label: "TF4" },
  { id: "tf5", label: "TF5" },
  { id: "tf6", label: "TF6" },
  { id: "tf7", label: "TF7" },
];

const BASE_SORT: Array<{ id: SortKey; label: string }> = [
  { id: "overall", label: "Overall score" },
  { id: "race", label: "Race score" },
  { id: "qualifying", label: "Qualifying score" },
];

const TF_COLORS = ["#a3e635", "#818cf8", "#ff7eb6", "#ffb020", "#c084fc", "#22d3ee", "#fb923c"];

function raceScoreMode(race: RaceListItem | null | undefined): ScoreMode {
  return race?.score_mode === "tf" ? "tf" : "psv";
}

function sortOptionsFor(mode: ScoreMode): Array<{ id: SortKey; label: string }> {
  return [...BASE_SORT, ...(mode === "tf" ? TF_SORT : PSV_SORT)];
}

function pairSum(left: number | null | undefined, right: number | null | undefined): number | null {
  if (left == null || right == null) {
    return null;
  }
  return left + right;
}

function sortValue(row: SelectedRaceRow, key: SortKey): number | null {
  if (key === "race") {
    return row.race_score;
  }
  if (key === "overall") {
    return row.overall_score;
  }
  if (key === "qualifying") {
    return row.qualifying_score;
  }
  if (key === "product") {
    return row.product;
  }
  if (key === "shop") {
    return row.shop;
  }
  if (key === "voucher") {
    return row.voucher;
  }
  if (key === "tf1") {
    return row.tf1 ?? null;
  }
  if (key === "tf2") {
    return row.tf2 ?? null;
  }
  if (key === "tf3") {
    return row.tf3 ?? null;
  }
  if (key === "tf4") {
    return row.tf4 ?? null;
  }
  if (key === "tf5") {
    return row.tf5 ?? null;
  }
  if (key === "tf6") {
    return row.tf6 ?? null;
  }
  if (key === "tf7") {
    return row.tf7 ?? null;
  }
  if (key === "ps") {
    return pairSum(row.product, row.shop);
  }
  if (key === "pv") {
    return pairSum(row.product, row.voucher);
  }
  return pairSum(row.shop, row.voucher);
}

function officialRank(row: SelectedRaceRow): number {
  return row.rank ?? Number.POSITIVE_INFINITY;
}

function compareBySort(a: SelectedRaceRow, b: SelectedRaceRow, key: SortKey): number {
  const aRaced = a.race_score != null;
  const bRaced = b.race_score != null;
  if (aRaced !== bRaced) {
    return aRaced ? -1 : 1;
  }
  const av = sortValue(a, key);
  const bv = sortValue(b, key);
  if (av == null && bv == null) {
    return officialRank(a) - officialRank(b);
  }
  if (av == null) {
    return 1;
  }
  if (bv == null) {
    return -1;
  }
  if (bv !== av) {
    return bv - av;
  }
  return officialRank(a) - officialRank(b);
}

function SortCombo({
  value,
  onChange,
  mode,
}: {
  value: SortKey;
  onChange: (key: SortKey) => void;
  mode: ScoreMode;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const options = sortOptionsFor(mode);
  const current = options.find((item) => item.id === value)?.label ?? "Overall score";

  useEffect(() => {
    if (!open) {
      return;
    }
    const onDoc = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  return (
    <Box
      ref={rootRef}
      sx={{
        display: "inline-flex",
        alignItems: "center",
        gap: 0.8,
        flex: "0 0 auto",
        position: "relative",
        mr: 0.5,
      }}
    >
      <Box sx={{ color: MUTED, fontSize: "0.78rem", fontWeight: 500, whiteSpace: "nowrap" }}>
        Sort
      </Box>
      <Box
        component="button"
        type="button"
        onClick={() => setOpen((on) => !on)}
        sx={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 1.25,
          height: 28,
          minWidth: 128,
          px: 1,
          border: "1px solid #2e343c",
          borderRadius: "6px",
          backgroundColor: "#0b0e12",
          color: "#ffffff",
          cursor: "pointer",
          font: "inherit",
          fontSize: "0.78rem",
          fontWeight: 500,
          whiteSpace: "nowrap",
          "&:hover": {
            borderColor: "#3a424c",
            color: "#ffffff",
          },
        }}
      >
        {current}
        <KeyboardArrowDown sx={{ fontSize: 16, color: "#ffffff" }} />
      </Box>
      {open ? (
        <Box
          sx={{
            position: "absolute",
            top: "calc(100% + 6px)",
            left: 36,
            zIndex: 20,
            minWidth: 148,
            border: "1px solid #2a3038",
            borderRadius: "8px",
            backgroundColor: "#12171d",
            boxShadow: "0 8px 24px rgba(0,0,0,0.45)",
            overflow: "hidden",
          }}
        >
          {options.map((item) => {
            const active = item.id === value;
            return (
              <Box
                key={item.id}
                component="button"
                type="button"
                onClick={() => {
                  onChange(item.id);
                  setOpen(false);
                }}
                sx={{
                  display: "block",
                  width: "100%",
                  textAlign: "left",
                  px: 1.1,
                  py: 0.65,
                  border: 0,
                  backgroundColor: active ? "#1a2028" : "transparent",
                  color: active ? "#ffffff" : "#c5c9d0",
                  cursor: "pointer",
                  font: "inherit",
                  fontSize: "0.78rem",
                  fontWeight: active ? 600 : 500,
                  "&:hover": { backgroundColor: "#1a2028", color: "#ffffff" },
                }}
              >
                {item.label}
              </Box>
            );
          })}
        </Box>
      ) : null}
    </Box>
  );
}

function GroupCombo({
  groups,
  selected,
  onChange,
}: {
  groups: KeyGroup[];
  selected: string[];
  onChange: (labels: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const selectedSet = new Set(selected);
  const allOn = groups.length > 0 && selected.length === groups.length;
  const filtered = !allOn;

  useEffect(() => {
    if (!open) {
      return;
    }
    const onDoc = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  return (
    <Box ref={rootRef} sx={{ position: "relative", flex: "0 0 auto" }}>
      <Box
        component="button"
        type="button"
        onClick={() => setOpen((value) => !value)}
        sx={{
          display: "inline-flex",
          alignItems: "center",
          gap: 0.7,
          height: 28,
          px: 1,
          border: filtered ? `1px solid ${ORANGE}` : "1px solid #2e343c",
          borderRadius: "7px",
          backgroundColor: "#161b22",
          color: filtered ? ORANGE : "#c5c9d0",
          cursor: "pointer",
          font: "inherit",
          fontSize: "0.78rem",
          fontWeight: 600,
          whiteSpace: "nowrap",
          "&:hover": {
            borderColor: filtered ? ORANGE : "#3a424c",
            color: filtered ? ORANGE : "#ffffff",
          },
        }}
      >
        <Groups sx={{ fontSize: 16, color: filtered ? ORANGE : MUTED }} />
        Group
        <Box
          component="span"
          sx={{
            minWidth: "1.25em",
            color: ORANGE,
            fontWeight: 700,
            textAlign: "center",
            visibility: filtered ? "visible" : "hidden",
          }}
        >
          {selected.length}
        </Box>
        <KeyboardArrowDown sx={{ fontSize: 18, color: filtered ? ORANGE : MUTED, ml: 0.15 }} />
      </Box>
      {open ? (
        <Box
          sx={{
            position: "absolute",
            top: "calc(100% + 6px)",
            left: "auto",
            right: 0,
            zIndex: 20,
            width: 220,
            maxHeight: 280,
            display: "flex",
            flexDirection: "column",
            border: "1px solid #2a3038",
            borderRadius: "8px",
            backgroundColor: "#12171d",
            boxShadow: "0 8px 24px rgba(0,0,0,0.45)",
            overflow: "hidden",
          }}
        >
          <Box
            component="button"
            type="button"
            onClick={() => onChange(groups.map((group) => group.label))}
            sx={{
              display: "flex",
              alignItems: "center",
              gap: 0.75,
              px: 1.1,
              py: 0.7,
              border: 0,
              backgroundColor: "transparent",
              color: ORANGE,
              cursor: "pointer",
              font: "inherit",
              fontSize: "0.78rem",
              fontWeight: 600,
              "&:hover": { backgroundColor: "#1a2028" },
            }}
          >
            <Check sx={{ fontSize: 16 }} />
            Select all
          </Box>
          <Box
            component="button"
            type="button"
            onClick={() => onChange([])}
            sx={{
              display: "flex",
              alignItems: "center",
              gap: 0.75,
              px: 1.1,
              py: 0.7,
              border: 0,
              backgroundColor: "transparent",
              color: "#f06666",
              cursor: "pointer",
              font: "inherit",
              fontSize: "0.78rem",
              fontWeight: 600,
              "&:hover": { backgroundColor: "#1a2028" },
            }}
          >
            <Close sx={{ fontSize: 15 }} />
            Clear all
          </Box>
          <Box
            sx={{
              height: "1px",
              backgroundColor: "#3d4654",
              mx: 1,
              my: 0.25,
              flexShrink: 0,
            }}
          />
          <Box
            sx={{
              overflowY: "auto",
              maxHeight: 200,
              scrollbarWidth: "thin",
              scrollbarColor: "#4a5563 transparent",
              "&::-webkit-scrollbar": { width: 8 },
              "&::-webkit-scrollbar-thumb": {
                backgroundColor: "#c5c9d0",
                borderRadius: "8px",
              },
            }}
          >
            {groups.length ? (
              groups.map((group) => {
                const checked = selectedSet.has(group.label);
                return (
                  <Box
                    key={group.label}
                    component="label"
                    sx={{
                      display: "flex",
                      alignItems: "center",
                      gap: 0.85,
                      px: 1.1,
                      py: 0.65,
                      cursor: "pointer",
                      "&:hover": { backgroundColor: "#1a2028" },
                    }}
                  >
                    <Box
                      component="input"
                      type="checkbox"
                      checked={checked}
                      onChange={() =>
                        onChange(
                          checked
                            ? selected.filter((label) => label !== group.label)
                            : [...selected, group.label],
                        )
                      }
                      sx={{
                        width: 14,
                        height: 14,
                        margin: 0,
                        accentColor: ORANGE,
                        cursor: "pointer",
                        flexShrink: 0,
                      }}
                    />
                    <Box
                      sx={{
                        width: 8,
                        height: 8,
                        borderRadius: "50%",
                        backgroundColor: group.color,
                        flexShrink: 0,
                      }}
                    />
                    <Box
                      sx={{
                        color: "#c5c9d0",
                        fontSize: "0.78rem",
                        fontWeight: 500,
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                    >
                      {group.label}
                    </Box>
                  </Box>
                );
              })
            ) : (
              <Typography sx={{ color: MUTED, fontSize: "0.72rem", px: 1.1, py: 1 }}>
                No groups on My Keys
              </Typography>
            )}
          </Box>
        </Box>
      ) : null}
    </Box>
  );
}

function formatPct(value: number | null): string {
  if (value == null) {
    return "-";
  }
  return `${(value <= 1 ? value * 100 : value).toFixed(1)}%`;
}

function formatCompleted(value: string | null): string | null {
  if (!value) {
    return null;
  }
  const stamp = Date.parse(value);
  if (!Number.isFinite(stamp)) {
    return null;
  }
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(new Date(stamp));
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  return `${get("year")}/${get("month")}/${get("day")} ${get("hour")}:${get("minute")} JST`;
}

function splitAgentVersion(name: string): { base: string; version: string } {
  const match = name.match(/(_v\d+)$/i);
  if (!match) {
    return { base: name, version: "" };
  }
  return { base: name.slice(0, -match[1].length), version: match[1] };
}

function LeaderRow({
  label,
  name,
  score,
}: {
  label: string;
  name: string | null;
  score: number | null;
}) {
  const parts = name ? splitAgentVersion(name) : null;
  return (
    <Box sx={{ display: "flex", alignItems: "baseline", gap: 1, minWidth: 0 }}>
      <Typography
        sx={{
          color: ORANGE,
          fontSize: "0.78rem",
          fontWeight: 700,
          lineHeight: 1.35,
          width: 58,
          flexShrink: 0,
        }}
      >
        {label}
      </Typography>
      <Typography
        sx={{
          color: MUTED,
          fontSize: "0.75rem",
          fontFamily: mono,
          lineHeight: 1.35,
          minWidth: 0,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {name && score != null ? (
          <>
            <Box component="span" sx={{ color: "#ffffff" }}>
              {parts?.base}
            </Box>
            {parts?.version ? (
              <Box component="span" sx={{ color: "#6b717a" }}>
                {parts.version}
              </Box>
            ) : null}
            <Box component="span" sx={{ mx: 0.6 }}>
              ·
            </Box>
            {formatPct(score)}
          </>
        ) : (
          "-"
        )}
      </Typography>
    </Box>
  );
}

function formatPsvMid(value: number | null): string {
  if (value == null) {
    return "—";
  }
  if (value >= 0 && value <= 1) {
    return value.toFixed(2);
  }
  return value.toFixed(1);
}

function ScoreMidRow({
  items,
}: {
  items: Array<{ letter: string; color: string; value: number | null }>;
}) {
  return (
    <Box sx={{ display: "flex", alignItems: "flex-start", gap: 1, minWidth: 0 }}>
      <Typography
        sx={{
          color: ORANGE,
          fontSize: "0.68rem",
          fontWeight: 700,
          lineHeight: 1.35,
          width: 58,
          flexShrink: 0,
        }}
      >
        Mid
      </Typography>
      <Box
        sx={{
          display: "flex",
          alignItems: "baseline",
          flexWrap: "wrap",
          columnGap: 0.9,
          rowGap: 0.15,
          fontSize: "0.62rem",
          lineHeight: 1.35,
          minWidth: 0,
        }}
      >
        {items.map((entry) => (
          <Box
            key={entry.letter}
            sx={{ display: "inline-flex", alignItems: "baseline", gap: 0.35 }}
          >
            <Box component="span" sx={{ color: entry.color, fontWeight: 700 }}>
              {entry.letter}
            </Box>
            <Box component="span" sx={{ color: "#ffffff", fontFamily: mono, fontWeight: 600 }}>
              {formatPsvMid(entry.value)}
            </Box>
          </Box>
        ))}
      </Box>
    </Box>
  );
}

function RaceCard({
  race,
  latest,
  active,
  onSelect,
}: {
  race: RaceListItem;
  latest: boolean;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <Box
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect();
        }
      }}
      sx={{
        display: "block",
        width: "100%",
        flexShrink: 0,
        overflow: "visible",
        textAlign: "left",
        border: active ? "1px solid #e89b25" : "1px solid #232830",
        borderRadius: "8px",
        px: 1.35,
        py: 1.1,
        cursor: "pointer",
        backgroundColor: active ? "#1c2535" : "#161c28",
        color: "#c5c9d0",
        "&:hover": {
          backgroundColor: active ? "#1c2535" : "#1a2230",
        },
      }}
    >
      <Box sx={{ display: "flex", alignItems: "center", gap: 0.85, minWidth: 0 }}>
        <Typography
          sx={{
            color: "#ffffff",
            fontSize: "0.92rem",
            fontWeight: 700,
            lineHeight: 1.2,
            flexShrink: 0,
          }}
        >
          Race {race.race_number ?? "—"}
        </Typography>
        {latest ? (
          <Box
            sx={{
              px: 0.55,
              py: 0.1,
              border: "1px solid #e89b25",
              borderRadius: "3px",
              color: ORANGE,
              fontSize: "0.58rem",
              fontWeight: 700,
              letterSpacing: "0.06em",
              lineHeight: 1.4,
              flexShrink: 0,
            }}
          >
            LATEST
          </Box>
        ) : null}
        <Typography
          sx={{
            color: MUTED,
            fontSize: "0.72rem",
            lineHeight: 1.2,
            whiteSpace: "nowrap",
          }}
        >
          {race.agent_count.toLocaleString("en-US")} agents
        </Typography>
      </Box>
      <Box sx={{ mt: 0.7, display: "flex", flexDirection: "column", gap: 0.15 }}>
        <LeaderRow label="Overall" name={race.overall_agent} score={race.overall_score} />
        <LeaderRow label="Race" name={race.race_agent} score={race.race_score} />
        {raceScoreMode(race) === "tf" ? (
          <ScoreMidRow
            items={[
              { letter: "TF1", color: TF_COLORS[0], value: race.tf1_mid ?? null },
              { letter: "TF2", color: TF_COLORS[1], value: race.tf2_mid ?? null },
              { letter: "TF3", color: TF_COLORS[2], value: race.tf3_mid ?? null },
              { letter: "TF4", color: TF_COLORS[3], value: race.tf4_mid ?? null },
              { letter: "TF5", color: TF_COLORS[4], value: race.tf5_mid ?? null },
              { letter: "TF6", color: TF_COLORS[5], value: race.tf6_mid ?? null },
              { letter: "TF7", color: TF_COLORS[6], value: race.tf7_mid ?? null },
            ]}
          />
        ) : (
          <ScoreMidRow
            items={[
              { letter: "P", color: "#3ecf8e", value: race.p_mid },
              { letter: "S", color: "#4ea1ff", value: race.s_mid },
              { letter: "V", color: "#ff7eb6", value: race.v_mid },
            ]}
          />
        )}
      </Box>
    </Box>
  );
}

export default function OverallPage() {
  const [races, setRaces] = useState<RaceListItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState(false);
  const [updatingInfo, setUpdatingInfo] = useState(false);
  const [infoText, setInfoText] = useState("");
  const [updateDots, setUpdateDots] = useState(1);
  const [updateInfo, setUpdateInfo] = useState("Race #— data is loading");
  const [updateNotice, setUpdateNotice] = useState("");
  const [tableRows, setTableRows] = useState<SelectedRaceRow[]>([]);
  const [tableLoading, setTableLoading] = useState(false);
  const [tableTick, setTableTick] = useState(0);
  const [hideEliminated, setHideEliminated] = useState(false);
  const [publicOnly, setPublicOnly] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>("overall");
  const [query, setQuery] = useState("");
  const [selectedGroups, setSelectedGroups] = useState<string[] | null>(null);
  const knownGroupLabels = useRef<Set<string>>(new Set());
  const { rows: keyRows } = useMyMiners();
  const selectedRace = races.find((row) => row.race_id === selectedId) ?? null;
  const selectedMode = raceScoreMode(selectedRace);

  const groups = useMemo<KeyGroup[]>(() => {
    const byLabel = new Map<string, { label: string; color: string; at: number; ss58s: Set<string> }>();
    for (const row of keyRows) {
      const label = keyGroupLabel(row);
      if (!label) {
        continue;
      }
      const at = row.sort ?? (Date.parse(row.created_at) || 0);
      const existing = byLabel.get(label);
      if (!existing) {
        byLabel.set(label, {
          label,
          color: row.color || "#4ea1ff",
          at,
          ss58s: new Set(row.ss58 ? [row.ss58] : []),
        });
        continue;
      }
      if (row.ss58) {
        existing.ss58s.add(row.ss58);
      }
      if (at < existing.at) {
        existing.at = at;
        existing.color = row.color || existing.color;
      }
    }
    const named = [...byLabel.values()]
      .filter((group) => group.label !== NO_GROUP)
      .sort((a, b) => a.at - b.at)
      .map(({ label, color, ss58s }) => ({ label, color, ss58s }));
    return [
      ...named,
      { label: NO_GROUP, color: MUTED, ss58s: new Set<string>() },
    ];
  }, [keyRows]);

  const allGroupLabels = useMemo(() => groups.map((group) => group.label), [groups]);
  const activeGroups = selectedGroups ?? allGroupLabels;

  useEffect(() => {
    const labels = allGroupLabels;
    setSelectedGroups((current) => {
      if (current == null) {
        knownGroupLabels.current = new Set(labels);
        return null;
      }
      const added = labels.filter((label) => !knownGroupLabels.current.has(label));
      knownGroupLabels.current = new Set(labels);
      return [...current.filter((label) => labels.includes(label)), ...added];
    });
  }, [allGroupLabels]);

  const load = async (initial = false) => {
    if (initial) {
      setLoading(true);
    }
    const rows = finishedRaces(await fetchRacesList());
    setRaces(rows);
    setSelectedId((current) => current ?? rows[0]?.race_id ?? null);
    setLoading(false);
  };

  useEffect(() => {
    void load(true);
  }, []);

  useEffect(() => {
    if (!updating && !updatingInfo) {
      setUpdateDots(1);
      return;
    }
    const timer = window.setInterval(() => {
      setUpdateDots((dots) => (dots % 3) + 1);
    }, 450);
    return () => window.clearInterval(timer);
  }, [updating, updatingInfo]);

  useEffect(() => {
    if (!selectedId) {
      setTableRows([]);
      setTableLoading(false);
      return;
    }
    let cancelled = false;
    setTableLoading(true);
    setTableRows([]);
    void fetchRaceTable(selectedId).then((data) => {
      if (cancelled) {
        return;
      }
      setTableRows(data?.rows ?? []);
      setTableLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [selectedId, tableTick]);

  useEffect(() => {
    const psvKeys = new Set<SortKey>(["product", "shop", "voucher", "ps", "pv", "sv"]);
    const tfKeys = new Set<SortKey>(["tf1", "tf2", "tf3", "tf4", "tf5", "tf6", "tf7"]);
    setSortKey((key) => {
      if (selectedMode === "tf" && psvKeys.has(key)) {
        return "overall";
      }
      if (selectedMode === "psv" && tfKeys.has(key)) {
        return "overall";
      }
      return key;
    });
  }, [selectedMode]);

  const comboRankedRows = useMemo(
    () =>
      [...tableRows]
        .sort((a, b) => compareBySort(a, b, sortKey))
        .map((row, index) => ({ ...row, rank: index + 1 })),
    [tableRows, sortKey],
  );

  const rankedRows = useMemo(() => {
    const text = query.trim().toLowerCase();
    const selected = new Set(activeGroups);
    const groupedKeys = new Set<string>();
    const selectedKeys = new Set<string>();
    for (const group of groups) {
      if (group.label === NO_GROUP) {
        continue;
      }
      for (const key of group.ss58s) {
        groupedKeys.add(key);
        if (selected.has(group.label)) {
          selectedKeys.add(key);
        }
      }
    }
    const allGroupsOn = selected.size === groups.length;
    return comboRankedRows.filter((row) => {
      if (hideEliminated && row.eliminated === true) {
        return false;
      }
      if (publicOnly && row.code !== "public") {
        return false;
      }
      if (!allGroupsOn) {
        const inNamedGroup =
          (row.miner_hotkey && groupedKeys.has(row.miner_hotkey)) ||
          (row.coldkey && groupedKeys.has(row.coldkey));
        const inSelected =
          (row.miner_hotkey && selectedKeys.has(row.miner_hotkey)) ||
          (row.coldkey && selectedKeys.has(row.coldkey));
        if (inNamedGroup) {
          if (!inSelected) {
            return false;
          }
        } else if (!selected.has(NO_GROUP)) {
          return false;
        }
      }
      if (!text) {
        return true;
      }
      const name = (row.agent_name || "").toLowerCase();
      const hot = (row.miner_hotkey || "").toLowerCase();
      const cold = (row.coldkey || "").toLowerCase();
      return name.includes(text) || hot.includes(text) || cold.includes(text);
    });
  }, [comboRankedRows, hideEliminated, publicOnly, query, activeGroups, groups]);

  const updateRacesInfo = async () => {
    if (updatingInfo) {
      return;
    }
    setUpdatingInfo(true);
    setInfoText("Race info is loading");
    try {
      await startRacesInfoUpdate();
      for (;;) {
        const info = await fetchRacesInfoProgress();
        if (info.text) {
          setInfoText(info.text);
        }
        if (!info.updating) {
          break;
        }
        await new Promise((resolve) => window.setTimeout(resolve, 400));
      }
      const rows = finishedRaces(await fetchRacesList());
      setRaces(rows);
      setSelectedId((current) =>
        current && rows.some((row) => row.race_id === current)
          ? current
          : rows[0]?.race_id ?? null,
      );
    } finally {
      setUpdatingInfo(false);
    }
  };

  const updateDatabase = async () => {
    if (updating) {
      return;
    }
    if (!selectedId) {
      setUpdateNotice("Update Race Info!");
      window.setTimeout(() => setUpdateNotice(""), 2500);
      return;
    }
    const raceNumber = selectedRace?.race_number;
    const statusText = (number: number | string | null | undefined) =>
      `Race #${number ?? "—"} data is loading`;
    setUpdating(true);
    setUpdateNotice("");
    setUpdateInfo(statusText(raceNumber));
    try {
      await startRaceDatabaseUpdate(selectedId);
      for (;;) {
        const info = await fetchRacesUpdateProgress();
        if (info.race_number != null) {
          setUpdateInfo(statusText(info.race_number));
        } else if (info.text) {
          setUpdateInfo(info.text);
        }
        if (!info.updating) {
          break;
        }
        await new Promise((resolve) => window.setTimeout(resolve, 400));
      }
      const rows = finishedRaces(await fetchRacesList());
      setRaces(rows);
      setSelectedId((current) =>
        current && rows.some((row) => row.race_id === current) ? current : current,
      );
      setTableTick((tick) => tick + 1);
    } finally {
      setUpdating(false);
    }
  };

  return (
    <Box
      sx={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        minHeight: 0,
        backgroundColor: "#0b0e12",
        p: 1.25,
        position: "relative",
      }}
    >
      <Box
        sx={{
          display: "flex",
          flex: 1,
          minHeight: 0,
          gap: 1,
        }}
      >
      <Box
        sx={{
          width: 320,
          flexShrink: 0,
          height: "100%",
          minHeight: 0,
          display: "flex",
          flexDirection: "column",
          border: "1px solid #2a3038",
          borderRadius: "8px",
          backgroundColor: "#0b0e12",
          overflow: "hidden",
        }}
      >
        <Box
          sx={{
            flexShrink: 0,
            px: 1,
            pt: 1.15,
            pb: 0.85,
            borderBottom: "1px solid #2a3038",
          }}
        >
          <Box
            component="button"
            type="button"
            onClick={() => void updateRacesInfo()}
            disabled={updatingInfo}
            sx={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              height: 28,
              width: "100%",
              px: 1.2,
              border: updatingInfo ? `1px solid ${ORANGE}` : "1px solid #2e343c",
              borderRadius: "7px",
              backgroundColor: "#161b22",
              color: "#c5c9d0",
              cursor: updatingInfo ? "wait" : "pointer",
              font: "inherit",
              fontSize: "0.82rem",
              fontWeight: 600,
              letterSpacing: "0.02em",
              "&:disabled": {
                color: "#c5c9d0",
                border: `1px solid ${ORANGE}`,
                opacity: 1,
              },
              "&:hover": {
                color: "#ffffff",
                borderColor: ORANGE,
              },
            }}
          >
            <Box sx={{ position: "relative" }}>
              <Box sx={{ visibility: updatingInfo ? "hidden" : "visible" }}>
                Update Races Info
              </Box>
              <Box
                sx={{
                  position: "absolute",
                  inset: 0,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  visibility: updatingInfo ? "visible" : "hidden",
                }}
              >
                {`Updating${".".repeat(updateDots)}`}
              </Box>
            </Box>
          </Box>
          <Typography
            sx={{
              minHeight: 18,
              mt: 0.6,
              color: "#c5c9d0",
              fontSize: "0.75rem",
              fontWeight: 500,
              lineHeight: "18px",
              textAlign: "center",
            }}
          >
            {updatingInfo ? infoText || "Race info is loading" : "\u00a0"}
          </Typography>
        </Box>
        <Box
          sx={{
            flex: 1,
            minHeight: 0,
            display: "flex",
            flexDirection: "column",
            gap: 1,
            px: 1,
            py: 1.15,
            overflow: "auto",
            scrollbarWidth: "auto",
            scrollbarColor: "#4a5563 transparent",
            "&::-webkit-scrollbar": { width: 14, height: 14 },
            "&::-webkit-scrollbar-track": { backgroundColor: "transparent" },
            "&::-webkit-scrollbar-thumb": {
              backgroundColor: "#3d4654",
              borderRadius: "8px",
            },
          }}
        >
          {loading ? (
            <Box
              sx={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: 1.25,
                py: 4,
                color: ORANGE,
                fontSize: "0.78rem",
              }}
            >
              <CircularProgress size={16} sx={{ color: ORANGE }} />
              Loading
            </Box>
          ) : (
            races.map((race, index) => (
              <RaceCard
                key={race.race_id}
                race={race}
                latest={index === 0}
                active={race.race_id === selectedId}
                onSelect={() => setSelectedId(race.race_id)}
              />
            ))
          )}
        </Box>
      </Box>
      <Box
        sx={{
          flex: 1,
          minWidth: 0,
          height: "100%",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <Box
          sx={{
            display: "flex",
            alignItems: "flex-start",
            gap: 1.25,
            minWidth: 0,
          }}
        >
        <Box
          sx={{
            visibility: selectedRace ? "visible" : "hidden",
            flex: 1,
            minWidth: 0,
            border: "1px solid #2a3038",
            borderRadius: "8px",
            backgroundColor: "#12171d",
            px: 1.35,
            py: 1,
          }}
        >
          <Box
            sx={{
              display: "flex",
              alignItems: "flex-end",
              width: "100%",
            }}
          >
            <Box sx={{ flex: "0 0 auto" }}>
              <Typography
                sx={{
                  color: "#ffffff",
                  fontSize: "1.15rem",
                  fontWeight: 700,
                  lineHeight: 1.2,
                }}
              >
                {`Race #${selectedRace?.race_number ?? "—"}`}
              </Typography>
              <Typography
                sx={{
                  color: MUTED,
                  fontSize: "0.75rem",
                  fontWeight: 400,
                  lineHeight: 1.4,
                  mt: 0.5,
                  whiteSpace: "nowrap",
                }}
              >
                {(() => {
                  const when = formatCompleted(selectedRace?.completed_at ?? null);
                  const agents = `${(selectedRace?.agent_count ?? 0).toLocaleString("en-US")} agents`;
                  return when ? `Completed ${when} · ${agents}` : `Completed — · ${agents}`;
                })()}
              </Typography>
            </Box>
            <Box
              sx={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                flex: "0 0 auto",
                ml: 2,
                gap: 0.1,
              }}
            >
              <Typography
                sx={{
                  color: "#ffffff",
                  fontSize: "0.88rem",
                  fontWeight: 400,
                  whiteSpace: "nowrap",
                  lineHeight: 1.2,
                }}
              >
                anchor
              </Typography>
              <Typography
                sx={{
                  color: ORANGE,
                  fontSize: "1rem",
                  fontWeight: 700,
                  whiteSpace: "nowrap",
                  lineHeight: 1.2,
                }}
              >
                {(() => {
                  const value = selectedRace?.race_threshold;
                  if (value == null) {
                    return "—";
                  }
                  return `${(value <= 1 ? value * 100 : value).toFixed(2)}%`;
                })()}
              </Typography>
            </Box>
            <Box sx={{ flex: 1, minWidth: 8 }} />
            <Box
              sx={{
                display: "flex",
                alignItems: "center",
                flex: "0 0 auto",
                gap: 1.25,
              }}
            >
            <SortCombo value={sortKey} onChange={setSortKey} mode={selectedMode} />
            <Box
              component="button"
              type="button"
              aria-pressed={publicOnly}
              onMouseDown={(event) => event.preventDefault()}
              onClick={(event) => {
                event.currentTarget.blur();
                setPublicOnly((value) => !value);
              }}
              sx={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                height: 28,
                px: 0.85,
                ml: 2,
                flexShrink: 0,
                border: 0,
                boxShadow: publicOnly ? "0 0 0 1px #3ecf8e" : "0 0 0 1px #2e343c",
                borderRadius: "7px",
                color: publicOnly ? "#3ecf8e" : MUTED,
                backgroundColor: publicOnly ? "#163028" : "#161b22",
                fontSize: "0.75rem",
                fontWeight: 500,
                lineHeight: 1.4,
                cursor: "pointer",
                fontFamily: "inherit",
                outline: "none",
                whiteSpace: "nowrap",
                "&:focus, &:focus-visible, &:active": {
                  outline: "none",
                  boxShadow: publicOnly ? "0 0 0 1px #3ecf8e" : "0 0 0 1px #2e343c",
                  color: publicOnly ? "#3ecf8e" : MUTED,
                  backgroundColor: publicOnly ? "#163028" : "#161b22",
                },
              }}
            >
              public only
            </Box>
            <GroupCombo
              groups={groups}
              selected={activeGroups}
              onChange={setSelectedGroups}
            />
            <Box
              component="label"
              sx={{
                display: "inline-flex",
                alignItems: "center",
                height: 28,
                flex: "0 0 auto",
                gap: 0.7,
                color: "#c5c9d0",
                fontSize: "0.78rem",
                fontWeight: 600,
                cursor: "pointer",
                userSelect: "none",
                whiteSpace: "nowrap",
              }}
            >
              <Box
                component="input"
                type="checkbox"
                checked={hideEliminated}
                onChange={(event) => setHideEliminated(event.target.checked)}
                sx={{
                  width: 14,
                  height: 14,
                  margin: 0,
                  accentColor: ORANGE,
                  cursor: "pointer",
                }}
              />
              Hide eliminated
            </Box>
            <TextField
              size="small"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="name / coldkey / hotkey"
              slotProps={{
                input: {
                  startAdornment: (
                    <InputAdornment position="start">
                      <Search sx={{ fontSize: 16, color: "#8b949e" }} />
                    </InputAdornment>
                  ),
                  endAdornment: query ? (
                    <InputAdornment position="end">
                      <IconButton
                        size="small"
                        aria-label="Clear search"
                        onClick={() => setQuery("")}
                        sx={{
                          color: "#8a8f98",
                          p: 0.25,
                          "&:hover": { color: "#c5c9d0" },
                        }}
                      >
                        <Close sx={{ fontSize: 15 }} />
                      </IconButton>
                    </InputAdornment>
                  ) : null,
                },
              }}
              sx={{
                width: 240,
                flex: "0 0 auto",
                "& .MuiOutlinedInput-root": {
                  height: 28,
                  color: "#c5c9d0",
                  fontSize: "0.78rem",
                  backgroundColor: "#161b22",
                  borderRadius: "7px",
                  "& fieldset": { borderColor: "#2e343c", borderWidth: "1px !important" },
                  "&:hover fieldset": { borderColor: "#3a424c" },
                  "&.Mui-focused fieldset": { borderColor: ORANGE, borderWidth: "1px !important" },
                },
                "& .MuiOutlinedInput-input": {
                  py: 0.5,
                  "&::placeholder": { color: "#8b949e", opacity: 1 },
                },
              }}
            />
            <Box
              sx={{
                position: "relative",
                flexShrink: 0,
                display: "flex",
                flexDirection: "column",
                alignItems: "flex-end",
                gap: 0.35,
              }}
            >
              <Typography
                sx={{
                  minHeight: 16,
                  color: updateNotice ? ORANGE : "#c5c9d0",
                  fontSize: "0.72rem",
                  fontWeight: 500,
                  lineHeight: "16px",
                  whiteSpace: "nowrap",
                  visibility: updating || updateNotice ? "visible" : "hidden",
                }}
              >
                {updateNotice || updateInfo || "Race #— data is loading"}
              </Typography>
              <Box
                component="button"
                type="button"
                onClick={() => void updateDatabase()}
                disabled={updating}
                sx={{
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  height: 28,
                  px: 1.15,
                  border: updating ? `1px solid ${ORANGE}` : "1px solid #2e343c",
                  borderRadius: "7px",
                  backgroundColor: "#161b22",
                  color: "#c5c9d0",
                  cursor: updating ? "wait" : "pointer",
                  font: "inherit",
                  fontSize: "0.75rem",
                  fontWeight: 600,
                  letterSpacing: "0.02em",
                  whiteSpace: "nowrap",
                  "&:disabled": {
                    color: "#c5c9d0",
                    border: `1px solid ${ORANGE}`,
                    opacity: 1,
                  },
                  "&:hover": {
                    color: "#ffffff",
                    borderColor: ORANGE,
                  },
                }}
              >
                <Box sx={{ position: "relative" }}>
                  <Box sx={{ visibility: updating ? "hidden" : "visible" }}>
                    Update Race
                  </Box>
                  <Box
                    sx={{
                      position: "absolute",
                      inset: 0,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      visibility: updating ? "visible" : "hidden",
                    }}
                  >
                    {`Updating${".".repeat(updateDots)}`}
                  </Box>
                </Box>
              </Box>
            </Box>
            </Box>
          </Box>
        </Box>
        </Box>
        <Box
          sx={{
            flex: 1,
            minHeight: 0,
            mt: 1.25,
            overflow: "hidden",
            border: "1px solid #2a3038",
            borderRadius: "8px",
            backgroundColor: "#12171d",
          }}
        >
          <SelectedRaceTable
            rows={rankedRows}
            loading={tableLoading}
            showGroup={false}
            scoreMode={selectedMode}
          />
        </Box>
      </Box>
      </Box>
    </Box>
  );
}
