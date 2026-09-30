import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ArrowDownward from "@mui/icons-material/ArrowDownward";
import ArrowUpward from "@mui/icons-material/ArrowUpward";
import Close from "@mui/icons-material/Close";
import Refresh from "@mui/icons-material/Refresh";
import Search from "@mui/icons-material/Search";
import Box from "@mui/material/Box";
import IconButton from "@mui/material/IconButton";
import InputAdornment from "@mui/material/InputAdornment";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";

import {
  fetchCurrentRace,
  fetchRegisteredUids,
  type RaceStanding,
  type RegisteredUid,
  type SavedColdKey,
} from "../api";
import { useMyMiners } from "../myKeys";

const PAGE_SIZE = 60;
const COL_SIZE = 20;
const AGENT_COL = 200;
const RANK_COL = 42;
const Q_COL = 56;
const R_COL = 50;
const O_COL = 56;
const M_COL = 56;
const WIN_COL = 56;
const TABLE_WIDTH = RANK_COL + AGENT_COL + Q_COL + R_COL + O_COL + M_COL + WIN_COL;
const ORANGE = "#e89b25";
const GREEN = "#3ecf8e";
const YELLOW = "#f5d76e";
const RED = "#e85d75";
const MAIN = ORANGE;
const SURVIVOR_FRACTION = 0.35;

type SortKey = "rank" | "q" | "r" | "o" | "m" | "win";

type MarkedRow = RaceStanding & { mark: number };

const ROW_HEIGHT = 31;

const cellSx = {
  color: "#c5c9d0",
  borderColor: "#232830",
  backgroundColor: "#12171d",
  fontSize: "0.82rem",
  height: ROW_HEIGHT,
  py: 0,
  px: 0.85,
  whiteSpace: "nowrap",
  boxSizing: "border-box",
  lineHeight: 1.2,
} as const;

const HEAD_HEIGHT = 26;

const headSx = {
  ...cellSx,
  color: "#7d8590",
  fontWeight: 600,
  fontSize: "0.74rem",
  letterSpacing: "0.04em",
  height: HEAD_HEIGHT,
  py: 0,
} as const;

function keyGroupLabel(row: { nickname: string; group: string }): string {
  const nick = row.nickname.trim();
  if (nick) {
    return nick;
  }
  return row.group === "mine" ? "Po" : row.group;
}

function lookupSavedKey(
  keyBySs58: Map<string, SavedColdKey>,
  hotkey: string,
  coldkey: string,
): SavedColdKey | undefined {
  if (coldkey && keyBySs58.has(coldkey)) {
    return keyBySs58.get(coldkey);
  }
  if (hotkey && keyBySs58.has(hotkey)) {
    return keyBySs58.get(hotkey);
  }
  return undefined;
}

function standingKey(row: RaceStanding): string {
  return `${row.miner_hotkey}::${row.agent_name}::${row.version_number ?? ""}`;
}

function eliminationKeys(rows: RaceStanding[], active: boolean): Set<string> {
  if (!active) {
    return new Set();
  }
  const scored = [...rows]
    .filter((row) => row.race_score != null)
    .sort(
      (a, b) =>
        (b.race_score ?? 0) - (a.race_score ?? 0) ||
        (a.rank ?? 1e9) - (b.rank ?? 1e9),
    );
  if (!scored.length) {
    return new Set();
  }
  const cutoff = Math.max(1, Math.ceil(scored.length * SURVIVOR_FRACTION));
  const cutoffScore = scored[cutoff - 1].race_score ?? 0;
  return new Set(
    scored
      .filter((row) => (row.race_score ?? 0) < cutoffScore)
      .map(standingKey),
  );
}

function raceScoreColor(
  score: number | null,
  threshold: number | null,
  atRisk: boolean,
): string {
  if (score == null) {
    return GREEN;
  }
  if (threshold != null && score >= threshold) {
    return GREEN;
  }
  if (atRisk) {
    return RED;
  }
  return YELLOW;
}

function formatPct(value: number | null): string {
  if (value == null) {
    return "-";
  }
  return `${(value * 100).toFixed(1)}%`;
}

function winTotal(row: RaceStanding): number | null {
  const scores = (row.previous || [])
    .map((point) => point.score)
    .filter((score): score is number => score != null);
  if (!scores.length) {
    return null;
  }
  return scores.reduce((sum, score) => sum + score, 0);
}

function formatThreshold(value: number | null): string {
  if (value == null) {
    return "—";
  }
  return `${(value <= 1 ? value * 100 : value).toFixed(1)}%`;
}

function formatMargin(value: number | null): string {
  if (value == null || value === 0) {
    return "";
  }
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}`;
}

function marginColor(value: number | null): string {
  if (value == null) {
    return "#7d8590";
  }
  return value >= 0 ? GREEN : RED;
}

const tipSlot = {
  tooltip: {
    sx: {
      bgcolor: "#1c232b",
      color: "#c5c9d0",
      border: "1px solid #2e343c",
      boxShadow: "0 6px 18px rgba(0, 0, 0, 0.65)",
      px: 1.15,
      py: 0.8,
      opacity: "1 !important",
    },
  },
  arrow: {
    sx: { color: "#1c232b" },
  },
} as const;

function medalFill(rank: number): string | null {
  if (rank === 1) {
    return ORANGE;
  }
  if (rank === 2) {
    return "#9aa0a8";
  }
  if (rank === 3) {
    return "#5c636c";
  }
  return null;
}

function pageItems(current: number, total: number): Array<number | "ellipsis"> {
  if (total <= 7) {
    return Array.from({ length: total }, (_, index) => index + 1);
  }
  if (current <= 4) {
    return [1, 2, 3, 4, 5, 6, "ellipsis", total];
  }
  if (current >= total - 3) {
    return [1, "ellipsis", total - 5, total - 4, total - 3, total - 2, total - 1, total];
  }
  return [1, "ellipsis", current - 1, current, current + 1, "ellipsis", total];
}

function RankMark({ rank }: { rank: number }) {
  const fill = medalFill(rank);
  return (
    <Box
      sx={{
        width: 20,
        height: 20,
        borderRadius: "50%",
        backgroundColor: fill ?? "#3d4450",
        color: "#d8dce3",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: rank >= 100 ? "0.6rem" : "0.72rem",
        fontWeight: 400,
        lineHeight: 1,
        textAlign: "center",
      }}
    >
      {rank}
    </Box>
  );
}

function ScoreChart({
  points,
  raceNumber,
  margins = [],
  raceMargin,
}: {
  points: RaceStanding["previous"];
  raceNumber?: number | null;
  margins?: RaceStanding["margins"];
  raceMargin?: number | null;
}) {
  const current = points[0]?.race_number ?? raceNumber ?? null;
  const slots: RaceStanding["previous"] = [0, 1, 2].map((index) => {
    const point = points[index];
    const race = point?.race_number ?? (current != null ? current - index : null);
    return {
      race_number: race,
      score: point?.score ?? null,
    };
  });
  const max = Math.max(
    ...slots.map((point) => point.score ?? 0),
    0.01,
  );
  const marginByRace = new Map(
    margins
      .filter((point) => point.race_number != null)
      .map((point) => [point.race_number as number, point.score]),
  );

  const barMargin = (point: RaceStanding["previous"][number], index: number) => {
    if (point.race_number != null && marginByRace.has(point.race_number)) {
      return marginByRace.get(point.race_number) ?? null;
    }
    if (index === 0 && point.score != null && raceMargin != null) {
      return raceMargin;
    }
    return null;
  };

  const barColor = (margin: number | null) =>
    margin != null && margin < 0 ? RED : GREEN;

  return (
    <Tooltip
      title={
        <Box sx={{ fontSize: "0.75rem", lineHeight: 1.55 }}>
          {slots.map((point, index) => (
            <Box key={`${point.race_number}-${index}`}>
              <Box component="span" sx={{ color: "#c5c9d0" }}>
                {point.race_number != null ? `R#${point.race_number}` : "R#—"}
              </Box>
              {"  "}
              <Box
                component="span"
                sx={{ color: barColor(barMargin(point, index)), fontWeight: 600 }}
              >
                {point.score != null ? `${(point.score * 100).toFixed(1)}%` : "-"}
              </Box>
            </Box>
          ))}
        </Box>
      }
      placement="top"
      arrow
      slotProps={tipSlot}
    >
      <Box
        component="span"
        sx={{
          display: "inline-flex",
          gap: "2px",
          verticalAlign: "middle",
        }}
      >
        {slots.map((point, index) => {
          const score = point.score;
          const empty = score == null;
          const color = barColor(barMargin(point, index));
          const barHeight =
            score != null && score > 0
              ? Math.max(2, (score / max) * 16)
              : 0;
          return (
            <Box
              key={`${point.race_number}-${index}`}
              sx={{
                width: 6,
                height: 20,
                m: 0,
                p: 0,
                border: empty ? `0.5px solid ${color}` : "none",
                borderRadius: "1px",
                display: "flex",
                alignItems: "flex-end",
                justifyContent: "center",
                boxSizing: "border-box",
              }}
            >
              {barHeight ? (
                <Box
                  sx={{
                    width: "100%",
                    height: `${barHeight}px`,
                    backgroundColor: color,
                  }}
                />
              ) : null}
            </Box>
          );
        })}
      </Box>
    </Tooltip>
  );
}

function SortHead({
  label,
  active,
  desc,
  onClick,
  tooltip,
}: {
  label: string;
  active: boolean;
  desc: boolean;
  onClick: () => void;
  tooltip?: string;
}) {
  const button = (
    <Box
      component="button"
      type="button"
      onClick={onClick}
      sx={{
        display: "inline-flex",
        alignItems: "center",
        gap: 0.25,
        border: 0,
        background: "none",
        p: 0,
        color: active ? MAIN : "#7d8590",
        cursor: "pointer",
        font: "inherit",
        letterSpacing: "0.04em",
        fontWeight: 600,
        "&:hover": { color: active ? MAIN : "#c5c9d0" },
      }}
    >
      {label}
      {active ? (
        desc ? <ArrowDownward sx={{ fontSize: 10 }} /> : <ArrowUpward sx={{ fontSize: 10 }} />
      ) : null}
    </Box>
  );
  if (!tooltip) {
    return button;
  }
  return (
    <Tooltip title={tooltip} placement="top" arrow>
      {button}
    </Tooltip>
  );
}

function RaceColumn({
  rows,
  keys,
  raceNumber,
  threshold,
  atRisk,
  hideOverall,
  sortKey,
  sortDesc,
  onSort,
}: {
  rows: MarkedRow[];
  keys: SavedColdKey[];
  raceNumber: number | null;
  threshold: number | null;
  atRisk: Set<string>;
  hideOverall: boolean;
  sortKey: SortKey;
  sortDesc: boolean;
  onSort: (key: SortKey) => void;
}) {
  const keyBySs58 = useMemo(
    () => new Map(keys.map((row) => [row.ss58, row])),
    [keys],
  );

  return (
    <TableContainer sx={{ backgroundColor: "#12171d", overflow: "hidden", width: "100%" }}>
      <Table
        size="small"
        sx={{
          tableLayout: "fixed",
          width: "100%",
          minWidth: TABLE_WIDTH,
          backgroundColor: "#12171d",
        }}
      >
        <TableHead>
          <TableRow>
            <TableCell sx={{ ...headSx, width: RANK_COL, minWidth: RANK_COL, maxWidth: RANK_COL, px: 0.5, textAlign: "center" }}>
              <Tooltip title="sort rank in current table" placement="top" arrow>
                <Box component="span" sx={{ cursor: "default" }}>
                  #
                </Box>
              </Tooltip>
            </TableCell>
            <TableCell sx={{ ...headSx, minWidth: AGENT_COL }}>
              AGENT
            </TableCell>
            <TableCell sx={{ ...headSx, width: Q_COL, minWidth: Q_COL, maxWidth: Q_COL, textAlign: "center" }}>
              <SortHead
                label="Q"
                tooltip="qualifying score"
                active={sortKey === "q"}
                desc={sortDesc}
                onClick={() => onSort("q")}
              />
            </TableCell>
            <TableCell sx={{ ...headSx, width: R_COL, minWidth: R_COL, maxWidth: R_COL, textAlign: "center" }}>
              <SortHead
                label="R"
                tooltip="race score"
                active={sortKey === "r"}
                desc={sortDesc}
                onClick={() => onSort("r")}
              />
            </TableCell>
            <TableCell sx={{ ...headSx, width: O_COL, minWidth: O_COL, maxWidth: O_COL, textAlign: "center" }}>
              <SortHead
                label="O"
                tooltip="overall score"
                active={sortKey === "o"}
                desc={sortDesc}
                onClick={() => onSort("o")}
              />
            </TableCell>
            <TableCell sx={{ ...headSx, width: M_COL, minWidth: M_COL, maxWidth: M_COL, textAlign: "center" }}>
              <SortHead
                label="M"
                tooltip="sum of the previous race and the race before that"
                active={sortKey === "m"}
                desc={sortDesc}
                onClick={() => onSort("m")}
              />
            </TableCell>
            <TableCell sx={{ ...headSx, width: WIN_COL, minWidth: WIN_COL, maxWidth: WIN_COL, textAlign: "center" }}>
              <SortHead
                label="WIN"
                tooltip="last three race score"
                active={sortKey === "win"}
                desc={sortDesc}
                onClick={() => onSort("win")}
              />
            </TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((row) => {
            const saved = lookupSavedKey(keyBySs58, row.miner_hotkey, row.coldkey);
            const keyColor = saved?.color;
            const groupLabel = saved ? keyGroupLabel(saved) : "";
            const marginValue = row.margin;
            const margin = formatMargin(marginValue);
            return (
              <TableRow key={`${row.mark}-${row.miner_hotkey}`} sx={{ height: ROW_HEIGHT }}>
                <TableCell sx={{ ...cellSx, width: RANK_COL, minWidth: RANK_COL, maxWidth: RANK_COL, textAlign: "center" }}>
                  <RankMark rank={row.mark} />
                </TableCell>
                <TableCell
                  sx={{
                    ...cellSx,
                    minWidth: AGENT_COL,
                    overflow: "hidden",
                    whiteSpace: "nowrap",
                  }}
                >
                  <Box
                    sx={{
                      display: "flex",
                      alignItems: "center",
                      minWidth: 0,
                      overflow: "hidden",
                    }}
                  >
                    <Box
                      component={row.agent_version_id ? "a" : "span"}
                      href={
                        row.agent_version_id
                          ? `https://oroagents.com/agent/${row.agent_version_id}`
                          : undefined
                      }
                      target={row.agent_version_id ? "_blank" : undefined}
                      rel={row.agent_version_id ? "noopener noreferrer" : undefined}
                      title={row.agent_name}
                      sx={{
                        color: "#ffffff",
                        fontWeight: 700,
                        minWidth: 0,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        textDecoration: "none",
                        cursor: row.agent_version_id ? "pointer" : "default",
                        "&:hover": row.agent_version_id
                          ? { color: "#ffffff", textDecoration: "underline" }
                          : undefined,
                      }}
                    >
                      {row.agent_name}
                    </Box>
                    {row.version_number != null ? (
                      <Box
                        component="span"
                        sx={{ ml: 0.6, color: "#6b717a", fontSize: "0.74rem", flexShrink: 0 }}
                      >
                        v{row.version_number}
                      </Box>
                    ) : null}
                    {groupLabel ? (
                      <Box
                        component="span"
                        title={saved?.group === "other" ? "other" : "Po"}
                        sx={{
                          ml: 0.5,
                          px: 0.5,
                          py: 0,
                          height: 16,
                          borderRadius: "3px",
                          fontSize: "0.72rem",
                          fontWeight: 700,
                          lineHeight: 1,
                          letterSpacing: "0.01em",
                          color: keyColor || "#4ea1ff",
                          border: "none",
                          boxShadow: `inset 0 0 0 0.5px ${keyColor || "#4ea1ff"}`,
                          backgroundColor: "#161b22",
                          display: "inline-flex",
                          alignItems: "center",
                          boxSizing: "border-box",
                          flexShrink: 0,
                        }}
                      >
                        {groupLabel}
                      </Box>
                    ) : null}
                  </Box>
                </TableCell>
                <TableCell sx={{ ...cellSx, textAlign: "center" }}>{formatPct(row.qualifying_score)}</TableCell>
                <TableCell
                  sx={{
                    ...cellSx,
                    color: raceScoreColor(
                      row.race_score,
                      threshold,
                      atRisk.has(standingKey(row)),
                    ),
                    fontWeight: 700,
                    textAlign: "center",
                  }}
                >
                  {formatPct(row.race_score)}
                </TableCell>
                <TableCell sx={{ ...cellSx, color: GREEN, fontWeight: 700, textAlign: "center" }}>
                  {formatPct(hideOverall ? null : row.overall_score)}
                </TableCell>
                <TableCell
                  sx={{
                    ...cellSx,
                    color: marginColor(marginValue),
                    fontWeight: 600,
                    fontSize: "0.82rem",
                    textAlign: "center",
                  }}
                >
                  {row.margins?.length ? (
                    <Tooltip
                      title={
                        <Box sx={{ fontSize: "0.75rem", lineHeight: 1.55 }}>
                          {row.margins.map((point, index) => (
                            <Box key={`${point.race_number}-${index}`}>
                              <Box component="span" sx={{ color: "#c5c9d0" }}>
                                {point.race_number != null ? `R#${point.race_number}` : "R#—"}
                              </Box>
                              {"  "}
                              <Box
                                component="span"
                                sx={{ color: marginColor(point.score), fontWeight: 600 }}
                              >
                                {formatMargin(point.score)}
                              </Box>
                            </Box>
                          ))}
                        </Box>
                      }
                      placement="top"
                      arrow
                      slotProps={tipSlot}
                    >
                      <Box component="span" sx={{ cursor: "default" }}>
                        {margin}
                      </Box>
                    </Tooltip>
                  ) : (
                    margin
                  )}
                </TableCell>
                <TableCell sx={{ ...cellSx, textAlign: "center" }}>
                  <ScoreChart
                    points={row.previous}
                    raceNumber={raceNumber}
                    margins={row.margins}
                    raceMargin={row.race_margin}
                  />
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </TableContainer>
  );
}

export default function CurrentRaceTable() {
  const [rows, setRows] = useState<RaceStanding[]>([]);
  const [raceNumber, setRaceNumber] = useState<number | null>(null);
  const [raceStatus, setRaceStatus] = useState<string | null>(null);
  const [raceThreshold, setRaceThreshold] = useState<number | null>(null);
  const [qualifyingThreshold, setQualifyingThreshold] = useState<number | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [sortKey, setSortKey] = useState<SortKey>("m");
  const [sortDesc, setSortDesc] = useState(true);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [neurons, setNeurons] = useState<RegisteredUid[]>([]);
  const [selectedGroups, setSelectedGroups] = useState<string[]>([]);
  const loadBusy = useRef(false);

  const load = useCallback(async (refresh = false) => {
    if (loadBusy.current && !refresh) {
      return;
    }
    loadBusy.current = true;
    if (refresh) {
      setLoading(true);
    }
    try {
      const [data, uids] = await Promise.all([
        fetchCurrentRace(),
        fetchRegisteredUids(refresh),
      ]);
      if (data) {
        setRows(data.rows);
        setRaceNumber(data.race_number);
        setRaceStatus(data.race_status);
        setRaceThreshold(data.race_threshold);
        setQualifyingThreshold(data.qualifying_threshold);
        setTotal(data.total);
      }
      if (uids) {
        setNeurons(uids.rows ?? []);
      }
    } finally {
      loadBusy.current = false;
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const sortedRows = useMemo(() => {
    const value = (row: RaceStanding) => {
      if (sortKey === "q") {
        return row.qualifying_score;
      }
      if (sortKey === "r") {
        return row.race_score;
      }
      if (sortKey === "o") {
        return row.overall_score;
      }
      if (sortKey === "m") {
        return row.margin;
      }
      if (sortKey === "win") {
        return winTotal(row);
      }
      return row.rank;
    };
    return [...rows].sort((a, b) => {
      const av = value(a);
      const bv = value(b);
      if (av == null && bv == null) {
        return a.rank - b.rank;
      }
      if (av == null) {
        return 1;
      }
      if (bv == null) {
        return -1;
      }
      if (av === bv) {
        return a.rank - b.rank;
      }
      return sortDesc ? bv - av : av - bv;
    });
  }, [rows, sortKey, sortDesc]);

  const markedRows = useMemo<MarkedRow[]>(
    () => sortedRows.map((row, index) => ({ ...row, mark: index + 1 })),
    [sortedRows],
  );

  const { rows: keys } = useMyMiners();
  const groups = useMemo(() => {
    const byLabel = new Map<
      string,
      { label: string; color: string; at: number; ss58s: Set<string> }
    >();
    for (const row of keys) {
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
    const match = (ss58s: Set<string>, hotkey: string, coldkey: string) =>
      Boolean((coldkey && ss58s.has(coldkey)) || (hotkey && ss58s.has(hotkey)));
    return [...byLabel.values()]
      .sort((a, b) => a.at - b.at)
      .map((group) => ({
        label: group.label,
        color: group.color,
        ss58s: group.ss58s,
        agents: rows.filter((row) =>
          match(group.ss58s, row.miner_hotkey, row.coldkey),
        ).length,
        slots: neurons.filter((row) => match(group.ss58s, row.hotkey, row.coldkey)).length,
      }));
  }, [keys, neurons, rows]);

  const raceStatusText = (raceStatus || "").replace(/_/g, " ").toLowerCase();
  const raceRunning = raceStatusText === "race running";
  const liveRanking = raceStatusText === "live ranking";
  const atRisk = useMemo(
    () => eliminationKeys(rows, raceRunning || liveRanking),
    [liveRanking, raceRunning, rows],
  );

  const visibleRows = useMemo(() => {
    const text = query.trim().toLowerCase();
    const selected = new Set(selectedGroups);
    const selectedKeys = new Set<string>();
    if (selected.size) {
      for (const group of groups) {
        if (!selected.has(group.label)) {
          continue;
        }
        for (const key of group.ss58s) {
          selectedKeys.add(key);
        }
      }
    }
    return markedRows.filter((row) => {
      if (selectedKeys.size) {
        const inGroup =
          (row.coldkey && selectedKeys.has(row.coldkey)) ||
          (row.miner_hotkey && selectedKeys.has(row.miner_hotkey));
        if (!inGroup) {
          return false;
        }
      }
      if (!text) {
        return true;
      }
      const name = row.agent_name.toLowerCase();
      const version =
        row.version_number != null && row.version_number !== undefined
          ? String(row.version_number)
          : "";
      const labeled = version ? `${name}v${version}` : name;
      const labeledSpaced = version ? `${name} v${version}` : name;
      const hotkey = row.miner_hotkey.toLowerCase();
      const coldkey = (row.coldkey || "").toLowerCase();
      return (
        name.includes(text) ||
        labeled.includes(text) ||
        labeledSpaced.includes(text) ||
        text.includes(name) ||
        hotkey.includes(text) ||
        coldkey.includes(text)
      );
    });
  }, [groups, markedRows, query, selectedGroups]);

  const pageCount = Math.max(1, Math.ceil(visibleRows.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const start = safePage * PAGE_SIZE;
  const pageRows: MarkedRow[] = visibleRows.slice(start, start + PAGE_SIZE);
  const columns = [0, 1, 2].map((index) => pageRows.slice(index * COL_SIZE, (index + 1) * COL_SIZE));
  const from = pageRows[0]?.mark ?? 0;
  const to = pageRows[pageRows.length - 1]?.mark ?? 0;

  const onSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDesc((value) => !value);
    } else {
      setSortKey(key);
      setSortDesc(key !== "rank");
    }
    setPage(0);
  };
  const current = safePage + 1;
  const items = pageItems(current, pageCount);
  const threshold =
    raceRunning || liveRanking
      ? raceThreshold
      : qualifyingThreshold ?? raceThreshold;

  return (
    <Box>
      <Box sx={{ display: "flex", flexDirection: "column", gap: 1.35, mb: 1 }}>
        <Box
          sx={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 2,
            flexWrap: "wrap",
          }}
        >
          <Box sx={{ display: "flex", alignItems: "center", gap: 1.25, minWidth: 0 }}>
          <Typography
            sx={{
              color: "#ffffff",
              fontSize: "1.15rem",
              fontWeight: 700,
              lineHeight: 1.2,
              flexShrink: 0,
            }}
          >
            Race #{raceNumber ?? "—"}
          </Typography>
          <Box
            sx={{
              display: "inline-flex",
              alignItems: "center",
              gap: 0.75,
              height: 32,
              px: 1.25,
              flexShrink: 0,
              borderRadius: 999,
              backgroundColor: raceRunning ? "#163028" : "#3a2814",
            }}
          >
            <Box
              sx={{
                width: 7,
                height: 7,
                borderRadius: "50%",
                backgroundColor: raceRunning ? GREEN : "#e89b25",
                flexShrink: 0,
                boxShadow: raceRunning
                  ? "0 0 0 0 rgba(62, 207, 142, 0.65)"
                  : "0 0 0 0 rgba(232, 155, 37, 0.65)",
                animation: raceStatus ? "oroPulse 1.4s ease-out infinite" : "none",
                "@keyframes oroPulse": {
                  "0%": {
                    boxShadow: raceRunning
                      ? "0 0 0 0 rgba(62, 207, 142, 0.65)"
                      : "0 0 0 0 rgba(232, 155, 37, 0.65)",
                  },
                  "70%": {
                    boxShadow: raceRunning
                      ? "0 0 0 7px rgba(62, 207, 142, 0)"
                      : "0 0 0 7px rgba(232, 155, 37, 0)",
                  },
                  "100%": {
                    boxShadow: raceRunning
                      ? "0 0 0 0 rgba(62, 207, 142, 0)"
                      : "0 0 0 0 rgba(232, 155, 37, 0)",
                  },
                },
              }}
            />
            <Typography
              sx={{
                color: raceRunning ? GREEN : "#e89b25",
                fontSize: "0.82rem",
                fontWeight: 500,
                lineHeight: 1,
                whiteSpace: "nowrap",
              }}
            >
              {raceStatus ? raceStatus.replace(/_/g, " ").toLowerCase() : "—"}
            </Typography>
          </Box>
            <Box
              sx={{
                flexShrink: 0,
                display: "flex",
                flexDirection: "row",
                alignItems: "center",
                justifyContent: "center",
                gap: 0.6,
                minWidth: 92,
                height: 32,
                boxSizing: "border-box",
                px: 0.75,
                border: "1px solid #2e343c",
                borderRadius: "4px",
                backgroundColor: "#161b22",
                lineHeight: 1,
                whiteSpace: "nowrap",
              }}
            >
              <Box
                sx={{
                  color: "#ffffff",
                  fontSize: "0.88rem",
                  fontWeight: 400,
                  letterSpacing: "0.02em",
                  lineHeight: 1,
                }}
              >
                Agents
              </Box>
              <Box
                sx={{
                  color: "#ffffff",
                  fontSize: "0.95rem",
                  fontWeight: 600,
                  fontVariantNumeric: "tabular-nums",
                  lineHeight: 1,
                }}
              >
                {visibleRows.length}
              </Box>
            </Box>
            <Box
              sx={{
                flexShrink: 0,
                display: "flex",
                flexDirection: "row",
                alignItems: "center",
                justifyContent: "center",
                gap: 0.6,
                height: 32,
                boxSizing: "border-box",
                px: 0.75,
                border: "1px solid #2e343c",
                borderRadius: "4px",
                backgroundColor: "#161b22",
                lineHeight: 1,
                whiteSpace: "nowrap",
              }}
            >
              <Box
                sx={{
                  color: ORANGE,
                  fontSize: "0.88rem",
                  fontWeight: 700,
                  letterSpacing: "0.02em",
                  lineHeight: 1,
                }}
              >
                Threshold
              </Box>
              <Box
                sx={{
                  color: ORANGE,
                  fontSize: "0.88rem",
                  fontWeight: 600,
                  fontVariantNumeric: "tabular-nums",
                  lineHeight: 1,
                }}
              >
                {formatThreshold(threshold)}
              </Box>
            </Box>
          <Box
            component="button"
            type="button"
            onClick={() => void load(true)}
            disabled={loading}
            sx={{
              display: "inline-flex",
              alignItems: "center",
              gap: 0.5,
              height: 32,
              px: 1.1,
              ml: 10,
              flexShrink: 0,
              border: "1px solid #2e343c",
              borderRadius: "7px",
              backgroundColor: "#161b22",
              color: "#8b949e",
              cursor: loading ? "wait" : "pointer",
              opacity: loading ? 0.45 : 1,
              pointerEvents: loading ? "none" : "auto",
              font: "inherit",
              fontSize: "0.95rem",
              fontWeight: 600,
              letterSpacing: "0.02em",
              "&:hover": {
                color: loading ? "#8b949e" : "#c5c9d0",
                borderColor: loading ? "#2e343c" : ORANGE,
              },
            }}
          >
            <Refresh
              sx={{
                fontSize: 16,
                animation: loading ? "oroSpin 0.8s linear infinite" : "none",
                "@keyframes oroSpin": {
                  to: { transform: "rotate(360deg)" },
                },
              }}
            />
            refresh
          </Box>
          </Box>
        </Box>
        <Box
          sx={{
            display: "flex",
            alignItems: "flex-end",
            gap: 1.25,
            minWidth: 0,
          }}
        >
        <Box
          sx={{
            flex: 1,
            minWidth: 0,
            display: "flex",
            alignItems: "flex-end",
            gap: 0.75,
            overflowX: "auto",
            overflowY: "hidden",
            p: 0,
            m: 0,
            "&::-webkit-scrollbar": { height: 4 },
            "&::-webkit-scrollbar-thumb": {
              backgroundColor: "#3a424c",
              borderRadius: 999,
            },
            "&::-webkit-scrollbar-track": { backgroundColor: "transparent" },
          }}
        >
            <Box
              component="button"
              type="button"
              onClick={() => {
                setSelectedGroups([]);
                setPage(0);
              }}
              sx={{
                flexShrink: 0,
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                  m: 0,
                  px: 0.55,
                  py: 0.05,
                  borderRadius: "3px",
                  border: `1px solid ${selectedGroups.length ? "#2e343c" : "#8b949e"}`,
                  backgroundColor: "#161b22",
                  whiteSpace: "nowrap",
                  lineHeight: 1,
                  cursor: "pointer",
                  font: "inherit",
                "&:hover": {
                  borderColor: "#8b949e",
                },
              }}
            >
              <Box
                sx={{
                  color: "#c5c9d0",
                  fontSize: "0.72rem",
                  fontWeight: 700,
                  letterSpacing: "0.02em",
                }}
              >
                clear
              </Box>
              <Box
                sx={{
                  color: "#8b949e",
                  fontSize: "0.78rem",
                  fontWeight: 600,
                  fontVariantNumeric: "tabular-nums",
                  minWidth: `${String(rows.length).length + String(neurons.length).length + 1}ch`,
                  textAlign: "center",
                }}
              >
                {rows.length}/{neurons.length}
              </Box>
            </Box>
            {groups.map((group) => {
              const selected = selectedGroups.includes(group.label);
              return (
              <Box
                key={group.label}
                component="button"
                type="button"
                onClick={() => {
                  setSelectedGroups((current) =>
                    current.includes(group.label)
                      ? current.filter((label) => label !== group.label)
                      : [...current, group.label],
                  );
                  setPage(0);
                }}
                sx={{
                  flexShrink: 0,
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  justifyContent: "center",
                  m: 0,
                  px: 0.55,
                  py: 0.05,
                  borderRadius: "3px",
                  border: `1px solid ${selected ? group.color : "#2e343c"}`,
                  backgroundColor: "#161b22",
                  whiteSpace: "nowrap",
                  lineHeight: 1,
                  cursor: "pointer",
                  font: "inherit",
                  "&:hover": {
                    borderColor: group.color,
                  },
                }}
              >
                <Box
                  sx={{
                    color: group.color,
                    fontSize: "0.72rem",
                    fontWeight: 700,
                    letterSpacing: "0.02em",
                  }}
                >
                  {group.label}
                </Box>
                <Box
                  sx={{
                    color: "#8b949e",
                    fontSize: "0.78rem",
                    fontWeight: 600,
                    fontVariantNumeric: "tabular-nums",
                    minWidth: "4.5ch",
                    textAlign: "center",
                  }}
                >
                  {group.agents}/{group.slots}
                </Box>
              </Box>
              );
            })}
          </Box>
        <TextField
          size="small"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setPage(0);
          }}
          placeholder="Search miners by name, coldkey and hotkey."
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
                    onClick={() => {
                      setQuery("");
                      setPage(0);
                    }}
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
            width: 280,
            flexShrink: 0,
            "& .MuiOutlinedInput-root": {
              height: 32,
              color: "#c5c9d0",
              fontSize: "0.78rem",
              backgroundColor: "#161b22",
              borderRadius: "7px",
              "& fieldset": { borderColor: "#2e343c", borderWidth: "1px !important" },
              "&:hover fieldset": { borderColor: "#3a424c" },
              "&.Mui-focused fieldset": { borderColor: ORANGE },
            },
            "& .MuiOutlinedInput-input": {
              py: 0.5,
              "&::placeholder": { color: "#8b949e", opacity: 1 },
            },
          }}
        />
        </Box>
      </Box>
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr", lg: "minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1fr)" },
          columnGap: 1.5,
          rowGap: 1.5,
        }}
      >
        {columns.map((column, index) => {
          const colFrom = column[0]?.mark;
          const colTo = column[column.length - 1]?.mark;
          return (
          <Box
            key={index}
            sx={{
              overflow: "hidden",
              width: "100%",
              minWidth: 0,
              backgroundColor: "#12171d",
            }}
          >
            <Box
              sx={{
                px: 0.85,
                py: 0,
                height: HEAD_HEIGHT,
                boxSizing: "border-box",
                display: "flex",
                alignItems: "center",
                backgroundColor: "#1c2331",
                color: "#6e7681",
                fontSize: "0.72rem",
                fontWeight: 700,
                letterSpacing: "0.06em",
                textTransform: "uppercase",
              }}
            >
              {colFrom != null && colTo != null ? `RANKS ${colFrom}-${colTo}` : "RANKS"}
            </Box>
            <RaceColumn
              rows={column}
              keys={keys}
              raceNumber={raceNumber}
              threshold={threshold}
              atRisk={atRisk}
              hideOverall={raceRunning}
              sortKey={sortKey}
              sortDesc={sortDesc}
              onSort={onSort}
            />
          </Box>
          );
        })}
      </Box>
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 2,
          px: 0.5,
          pt: 1.25,
          pb: 0.25,
        }}
      >
        <Typography sx={{ color: "#8a8f98", fontSize: "0.78rem" }}>
          Ranks {from}–{to} of {total} - page {current}/{pageCount}
        </Typography>
        <Box sx={{ display: "flex", alignItems: "center", gap: 0.75 }}>
          <Box
            component="button"
            type="button"
            disabled={safePage <= 0}
            onClick={() => setPage(safePage - 1)}
            sx={{
              height: 26,
              px: 1.1,
              border: "1px solid #2a3038",
              borderRadius: "5px",
              backgroundColor: "#1c232b",
              color: safePage <= 0 ? "#4a5058" : "#c5c9d0",
              cursor: safePage <= 0 ? "default" : "pointer",
              fontSize: "0.75rem",
            }}
          >
            Prev
          </Box>
          {items.map((item, index) =>
            item === "ellipsis" ? (
              <Box key={`e-${index}`} sx={{ color: "#8a8f98", fontSize: "0.78rem" }}>
                …
              </Box>
            ) : (
              <Box
                key={item}
                component="button"
                type="button"
                onClick={() => setPage(item - 1)}
                sx={{
                  minWidth: 26,
                  height: 26,
                  boxSizing: "border-box",
                  border: item === current ? "1px solid #f0a500" : "1px solid transparent",
                  borderRadius: "4px",
                  backgroundColor: item === current ? "#7c5300" : "#1c232b",
                  color: item === current ? "#f0a500" : "#8a8f98",
                  fontSize: "0.75rem",
                  fontWeight: item === current ? 700 : 500,
                  cursor: "pointer",
                }}
              >
                {item}
              </Box>
            ),
          )}
          <Box
            component="button"
            type="button"
            disabled={safePage >= pageCount - 1}
            onClick={() => setPage(safePage + 1)}
            sx={{
              height: 26,
              px: 1.1,
              border: "1px solid #2a3038",
              borderRadius: "5px",
              backgroundColor: "#1c232b",
              color: safePage >= pageCount - 1 ? "#4a5058" : "#c5c9d0",
              cursor: safePage >= pageCount - 1 ? "default" : "pointer",
              fontSize: "0.75rem",
            }}
          >
            Next
          </Box>
        </Box>
      </Box>
    </Box>
  );
}
