import { useMemo, useState } from "react";
import Box from "@mui/material/Box";
import CircularProgress from "@mui/material/CircularProgress";
import Tooltip from "@mui/material/Tooltip";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";

import type { ScoreMode, SelectedRaceRow, TrendPoint } from "../api";
import { useMyMiners } from "../myKeys";
import TrendDialog from "./TrendDialog";

const GREEN = "#3ecf8e";
const RED = "#e85d75";
const RANK_COL = 48;
const AGENT_COL = 240;

function formatMargin(value: number | null | undefined): string {
  if (value == null) {
    return "-";
  }
  if (value === 0) {
    return "";
  }
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}`;
}

function marginColor(value: number | null | undefined): string {
  if (value == null) {
    return "#7d8590";
  }
  return value >= 0 ? GREEN : RED;
}

function keyGroupLabel(row: { nickname: string; group: string }): string {
  const nick = row.nickname.trim();
  if (nick) {
    return nick;
  }
  return row.group === "mine" ? "Po" : row.group;
}

const cellSx = {
  color: "#c5c9d0",
  borderColor: "#232830",
  backgroundColor: "#12171d",
  fontSize: "0.74rem",
  py: 1.2,
  px: 1.1,
  whiteSpace: "nowrap",
} as const;

const psvCellSx = {
  ...cellSx,
  px: 0,
} as const;

const psvFollowSx = {
  ...psvCellSx,
  pl: 0,
  ml: "-6px",
} as const;

const headSx = {
  ...cellSx,
  color: "#7d8590",
  fontWeight: 700,
  fontSize: "0.68rem",
  letterSpacing: "0.04em",
  py: 1.45,
  position: "sticky",
  top: 0,
  zIndex: 4,
  backgroundColor: "#12171d",
} as const;

function formatInt(value: number | null | undefined): string {
  if (value == null) {
    return "-";
  }
  return value.toLocaleString("en-US");
}

function formatPct(value: number | null): string {
  if (value == null) {
    return "-";
  }
  return `${(value * 100).toFixed(1)}%`;
}

function parseUtc(value: string): number {
  const text = value.trim();
  if (/[zZ]|[+-]\d{2}:\d{2}$/.test(text)) {
    return Date.parse(text);
  }
  return Date.parse(`${text.includes("T") ? text : text.replace(" ", "T")}Z`);
}

function SubmittedTime({ value }: { value: string | null }) {
  if (!value) {
    return <Box component="span">-</Box>;
  }
  const stamp = parseUtc(value);
  if (!Number.isFinite(stamp)) {
    return <Box component="span">{value}</Box>;
  }
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).formatToParts(new Date(stamp));
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  return (
    <Box sx={{ display: "flex", flexDirection: "column", alignItems: "center", lineHeight: 1.2, whiteSpace: "nowrap" }}>
      <Box>{`${get("year")}-${get("month")}-${get("day")}`}</Box>
      <Box>{`${get("hour")}:${get("minute")}:${get("second")} JST`}</Box>
    </Box>
  );
}

function trendScore(point: TrendPoint, key: "o" | "r"): number | null {
  const value = key === "o" ? (point.o_score ?? point.score) : (point.r_score ?? point.score);
  return value == null || !Number.isFinite(value) ? null : value;
}

function trendAvg(point: TrendPoint, key: "o" | "r"): number | null {
  const value = key === "o" ? point.o_mid : (point.anchor ?? point.r_mid);
  return value == null || !Number.isFinite(value) ? null : value;
}

function trendFrame(width: number, height: number) {
  return {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    boxSizing: "border-box",
    width: width + 20,
    height: height + 6,
    px: "8px",
    verticalAlign: "middle",
    border: "1px solid #272f4f",
    borderRadius: "4px",
    backgroundColor: "#0e1521",
    "&:hover": {
      borderColor: "#3d4a73",
      backgroundColor: "#182235",
    },
  } as const;
}

function DeltaTrendGraph({
  points,
  scoreKey,
}: {
  points?: TrendPoint[] | null;
  scoreKey: "o" | "r";
}) {
  const byRace = new Map<number, number>();
  const seen: number[] = [];
  for (const point of points ?? []) {
    const number = point.race_number;
    if (number == null) {
      continue;
    }
    const score = trendScore(point, scoreKey);
    const mid = trendAvg(point, scoreKey);
    if (score != null && mid != null) {
      if (!seen.includes(number)) {
        seen.push(number);
      }
      byRace.set(number, score - mid);
    }
  }
  seen.sort((a, b) => a - b);
  const slots: number[] = [];
  if (seen.length) {
    for (let number = seen[0]; number <= seen[seen.length - 1]; number += 1) {
      slots.push(number);
    }
  }
  const series = slots.map((race_number) => ({
    race_number,
    delta: byRace.has(race_number) ? byRace.get(race_number)! : null,
  }));
  const width = 168;
  const height = 50;
  const frame = trendFrame(width, height);
  const plotted = series.filter((point) => point.delta != null);
  if (!plotted.length) {
    return <Box component="span" sx={frame}>-</Box>;
  }
  const deltas = plotted.map((point) => point.delta as number);
  const yMin = Math.min(0, ...deltas);
  const yMax = Math.max(0, ...deltas);
  const span = yMax - yMin || 0.01;
  const plotTop = 6;
  const plotBottom = 34;
  const plotH = plotBottom - plotTop;
  const xAt = (index: number) =>
    series.length === 1 ? width / 2 : (index / (series.length - 1)) * (width - 22) + 11;
  const yAt = (value: number) => plotBottom - ((value - yMin) / span) * plotH;
  const y0 = yAt(0);
  const linePts = series
    .map((point, index) =>
      point.delta == null ? null : `${xAt(index)},${yAt(point.delta)}`,
    )
    .filter((value): value is string => value != null);
  return (
    <Box component="span" sx={frame}>
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
        <line
          x1={4}
          x2={width - 4}
          y1={y0}
          y2={y0}
          stroke="#5b6778"
          strokeWidth="1"
          strokeDasharray="3 3"
        />
        {linePts.length > 1 ? (
          <polyline
            fill="none"
            stroke="#3d4a73"
            strokeWidth="1.4"
            points={linePts.join(" ")}
          />
        ) : null}
        {series.map((point, index) => {
          if (point.delta == null) {
            return null;
          }
          const x = xAt(index);
          const marked = index === 0 || index === series.length - 1;
          return (
            <g key={`${point.race_number}-${index}`}>
              <circle
                cx={x}
                cy={yAt(point.delta)}
                r={3.2}
                fill={point.delta >= 0 ? "#34d399" : "#f77272"}
              />
              {marked ? (
                <text
                  x={x}
                  y={45}
                  textAnchor="middle"
                  fill="#8b949e"
                  fontSize="6.5"
                  fontWeight="600"
                >
                  {`R${point.race_number}`}
                </text>
              ) : null}
            </g>
          );
        })}
      </svg>
    </Box>
  );
}

function SparkLine({
  points,
  scoreKey,
  onOpen,
}: {
  points?: TrendPoint[] | null;
  scoreKey: "o" | "r";
  onOpen?: () => void;
}) {
  return (
    <Box
      component="button"
      type="button"
      onPointerDown={(event) => {
        event.preventDefault();
        event.stopPropagation();
        event.currentTarget.setPointerCapture(event.pointerId);
        onOpen?.();
      }}
      onClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
      }}
      sx={{
        border: 0,
        p: 0,
        m: 0,
        background: "none",
        cursor: onOpen ? "pointer" : "default",
        font: "inherit",
        verticalAlign: "middle",
      }}
    >
      <DeltaTrendGraph points={points} scoreKey={scoreKey} />
    </Box>
  );
}

function raceRange(points: TrendPoint[] | undefined): { first: number | null; last: number | null } {
  const numbers = [...new Set(
    (points ?? [])
      .map((point) => point.race_number)
      .filter((value): value is number => value != null),
  )].sort((a, b) => a - b);
  return {
    first: numbers[0] ?? null,
    last: numbers[numbers.length - 1] ?? null,
  };
}

function formatRaceList(points: TrendPoint[] | undefined): string[] {
  const numbers = [...new Set(
    (points ?? [])
      .map((point) => point.race_number)
      .filter((value): value is number => value != null),
  )].sort((a, b) => a - b);
  return numbers.map((value) => `race${value}`);
}

function formatPsv(value: number | null | undefined): string {
  if (value == null) {
    return "-";
  }
  // TF family means are 0-1 (official cards); legacy P/S/V stay on larger scales.
  if (value >= 0 && value <= 1) {
    return value.toFixed(2);
  }
  return value.toFixed(1);
}

function PsvColumnHead({
  letter,
  color,
  title,
}: {
  letter: string;
  color: string;
  title: string;
}) {
  return (
    <Box
      title={title}
      sx={{ display: "inline-flex", alignItems: "center", gap: "2px" }}
    >
      <Box
        sx={{
          color,
          fontWeight: 700,
          fontSize: "0.95rem",
          lineHeight: 1,
          minWidth: letter.length > 1 ? 34 : 28,
          textAlign: "center",
        }}
      >
        {letter}
      </Box>
    </Box>
  );
}

function PsvDiagram({
  score,
  color,
}: {
  score: number | null | undefined;
  color: string;
}) {
  return (
    <Box sx={{ color, fontWeight: 700, lineHeight: 1, minWidth: 28, textAlign: "center" }}>
      {formatPsv(score)}
    </Box>
  );
}

const TF_COLUMNS: Array<{ key: keyof SelectedRaceRow; letter: string; color: string; title: string }> = [
  { key: "tf1", letter: "TF1", color: "#a3e635", title: "TF1 intent" },
  { key: "tf2", letter: "TF2", color: "#818cf8", title: "TF2 retrieval" },
  { key: "tf3", letter: "TF3", color: "#ff7eb6", title: "TF3 constraint" },
  { key: "tf4", letter: "TF4", color: "#ffb020", title: "TF4 preference" },
  { key: "tf5", letter: "TF5", color: "#c084fc", title: "TF5 ranking" },
  { key: "tf6", letter: "TF6", color: "#22d3ee", title: "TF6 recovery" },
  { key: "tf7", letter: "TF7", color: "#fb923c", title: "TF7 justification" },
];

export default function SelectedRaceTable({
  rows,
  loading,
  activeVersionId,
  onPublicClick,
  showGroup = true,
  scoreMode = "psv",
}: {
  rows: SelectedRaceRow[];
  loading: boolean;
  activeVersionId?: string | null;
  onPublicClick?: (row: SelectedRaceRow) => void;
  showGroup?: boolean;
  scoreMode?: ScoreMode;
}) {
  const tfMode = scoreMode === "tf";
  const scoreColCount = tfMode ? TF_COLUMNS.length : 3;
  const colSpan = (showGroup ? 13 : 12) + scoreColCount;
  const { rows: keys } = useMyMiners();
  const keyBySs58 = useMemo(
    () => new Map(keys.map((row) => [row.ss58, row])),
    [keys],
  );
  const [trendOpen, setTrendOpen] = useState<{
    name: string;
    version: number | null;
    tab: "o" | "r";
    first: number | null;
    last: number | null;
    points: TrendPoint[];
  } | null>(null);
  return (
    <>
    <TableContainer
      sx={{
        backgroundColor: "#12171d",
        width: "100%",
        height: "100%",
        maxHeight: "100%",
        overflow: "auto",
        scrollbarWidth: "auto",
        scrollbarColor: "#4a5563 transparent",
        "&::-webkit-scrollbar": {
          width: 14,
          height: 14,
        },
        "&::-webkit-scrollbar-track": {
          backgroundColor: "transparent",
          margin: 6,
        },
        "&::-webkit-scrollbar-thumb": {
          backgroundColor: "#3d4654",
          borderRadius: "8px",
          border: "2px solid transparent",
          backgroundClip: "padding-box",
        },
        "&::-webkit-scrollbar-thumb:hover": {
          backgroundColor: "#5b6778",
        },
        "&::-webkit-scrollbar-corner": {
          backgroundColor: "transparent",
        },
      }}
    >
      <Table
        size="small"
        sx={{
          backgroundColor: "#12171d",
          width: "100%",
          tableLayout: "auto",
        }}
        stickyHeader
      >
        <TableHead>
          <TableRow>
            <TableCell
              sx={{
                ...headSx,
                width: RANK_COL,
                minWidth: RANK_COL,
                maxWidth: RANK_COL,
                px: 0.5,
                textAlign: "center",
              }}
              title="Race rank"
            >
              #
            </TableCell>
            <TableCell sx={{ ...headSx, width: AGENT_COL, minWidth: AGENT_COL, maxWidth: AGENT_COL }}>
              AGENT
            </TableCell>
            <TableCell sx={{ ...headSx, textAlign: "center" }}>CODE</TableCell>
            <TableCell sx={{ ...headSx, textAlign: "center" }}>LINES</TableCell>
            <TableCell sx={{ ...headSx, textAlign: "center" }} title="overall score of this race">
              O SCORE
            </TableCell>
            <TableCell sx={{ ...headSx, textAlign: "center" }}>R SCORE</TableCell>
            <TableCell sx={{ ...headSx, textAlign: "center" }}>Margin</TableCell>
            <TableCell sx={{ ...headSx, textAlign: "center" }}>Q SCORE</TableCell>
            {tfMode
              ? TF_COLUMNS.map((col, index) => (
                  <TableCell
                    key={col.key}
                    sx={{
                      ...(index === 0 ? psvCellSx : psvFollowSx),
                      ...headSx,
                      color: col.color,
                      py: 0.7,
                    }}
                  >
                    <PsvColumnHead letter={col.letter} color={col.color} title={col.title} />
                  </TableCell>
                ))
              : (
                  <>
                    <TableCell sx={{ ...headSx, ...psvCellSx, color: "#3ecf8e", py: 0.7 }}>
                      <PsvColumnHead letter="P" color="#3ecf8e" title="Product score" />
                    </TableCell>
                    <TableCell sx={{ ...headSx, ...psvFollowSx, color: "#4ea1ff", py: 0.7 }}>
                      <PsvColumnHead letter="S" color="#4ea1ff" title="Shop score" />
                    </TableCell>
                    <TableCell sx={{ ...headSx, ...psvFollowSx, color: "#ff7eb6", py: 0.7 }}>
                      <PsvColumnHead letter="V" color="#ff7eb6" title="Voucher score" />
                    </TableCell>
                  </>
                )}
            <TableCell sx={{ ...headSx, textAlign: "center" }}>SUBMITTED</TableCell>
            <TableCell sx={{ ...headSx, textAlign: "center" }}>RACES</TableCell>
            <TableCell sx={{ ...headSx, textAlign: "center" }}>O Trend</TableCell>
            <TableCell sx={{ ...headSx, textAlign: "center" }}>R Trend</TableCell>
            {showGroup ? <TableCell sx={headSx}>GROUP</TableCell> : null}
          </TableRow>
        </TableHead>
        <TableBody>
          {loading ? (
            <TableRow>
              <TableCell colSpan={colSpan} sx={{ ...cellSx, py: 6, textAlign: "center", color: "#e89b25" }}>
                <Box
                  sx={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 1.25,
                  }}
                >
                  <CircularProgress size={16} sx={{ color: "#e89b25" }} />
                  Loading
                </Box>
              </TableCell>
            </TableRow>
          ) : null}
          {loading
            ? null
            : rows.map((row, index) => (
            <TableRow
              key={row.agent_version_id || `${row.miner_hotkey}-${index}`}
              sx={{
                "&:hover td": {
                  backgroundColor: "#1c2535",
                },
              }}
            >
              <TableCell
                sx={{
                  ...cellSx,
                  width: RANK_COL,
                  minWidth: RANK_COL,
                  maxWidth: RANK_COL,
                  px: 0.5,
                  textAlign: "center",
                  color: row.rank === 1 ? "#e89b25" : cellSx.color,
                  fontWeight: row.rank === 1 ? 700 : 400,
                }}
              >
                {row.rank === 1 ? "TOP" : formatInt(row.rank)}
              </TableCell>
              <TableCell
                sx={{
                  ...cellSx,
                  width: AGENT_COL,
                  minWidth: AGENT_COL,
                  maxWidth: AGENT_COL,
                  overflow: "hidden",
                }}
              >
                {(() => {
                  const saved = keyBySs58.get(row.miner_hotkey) ?? keyBySs58.get(row.coldkey);
                  const groupLabel = saved ? keyGroupLabel(saved) : "";
                  return (
                    <Box
                      sx={{
                        display: "flex",
                        alignItems: "baseline",
                        width: "100%",
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
                          fontSize: "0.92rem",
                          lineHeight: 1.2,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                          minWidth: 0,
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
                          sx={{
                            ml: 0.5,
                            color: "#a8adb5",
                            fontSize: "0.78rem",
                            fontWeight: 600,
                            lineHeight: 1.2,
                            flexShrink: 0,
                          }}
                        >
                          v{row.version_number}
                        </Box>
                      ) : null}
                      {groupLabel ? (
                        <Box
                          component="span"
                          title={saved?.group === "other" ? "other" : "Po"}
                          sx={{
                            ml: 0.6,
                            px: 0.55,
                            py: 0.1,
                            borderRadius: "4px",
                            fontSize: "0.72rem",
                            fontWeight: 700,
                            lineHeight: 1.2,
                            letterSpacing: "0.02em",
                            color: saved?.color || "#4ea1ff",
                            border: "1px solid #2e343c",
                            backgroundColor: "#161b22",
                            flexShrink: 0,
                            alignSelf: "center",
                          }}
                        >
                          {groupLabel}
                        </Box>
                      ) : null}
                    </Box>
                  );
                })()}
              </TableCell>
              <TableCell sx={{ ...cellSx, textAlign: "center" }}>
                <Box
                  component={row.code === "public" ? "button" : "span"}
                  type={row.code === "public" ? "button" : undefined}
                  onClick={
                    row.code === "public"
                      ? () => onPublicClick?.(row)
                      : undefined
                  }
                  sx={
                    row.code === "public"
                      ? {
                          display: "inline-flex",
                          alignItems: "center",
                          px: 0.85,
                          py: 0.15,
                          border: 0,
                          boxShadow:
                            activeVersionId === row.agent_version_id
                              ? "0 0 0 1px #3ecf8e"
                              : "0 0 0 0.5px #3ecf8e",
                          borderRadius: "5px",
                          color: "#3ecf8e",
                          backgroundColor: "#163028",
                          fontSize: "0.70rem",
                          fontWeight: 700,
                          lineHeight: 1.4,
                          cursor: "pointer",
                          fontFamily: "inherit",
                        }
                      : {
                          display: "inline-flex",
                          alignItems: "center",
                          px: 0.85,
                          py: 0.15,
                          border: 0,
                          boxShadow: "0 0 0 0.5px #3a4048",
                          borderRadius: "5px",
                          color: "#6b717a",
                          backgroundColor: "transparent",
                          fontSize: "0.78rem",
                          fontWeight: 500,
                          lineHeight: 1.4,
                        }
                  }
                >
                  {row.code === "public" ? "Public" : "Private"}
                </Box>
              </TableCell>
              <TableCell sx={{ ...cellSx, textAlign: "center" }}>{formatInt(row.lines)}</TableCell>
              <TableCell sx={{ ...cellSx, color: GREEN, fontWeight: 700, textAlign: "center" }}>
                {formatPct(row.overall_score)}
              </TableCell>
              <TableCell sx={{ ...cellSx, color: GREEN, fontWeight: 700, textAlign: "center" }}>
                {formatPct(row.race_score)}
              </TableCell>
              <TableCell
                sx={{
                  ...cellSx,
                  color: marginColor(row.margin),
                  fontWeight: 600,
                  textAlign: "center",
                }}
              >
                {formatMargin(row.margin)}
              </TableCell>
              <TableCell sx={{ ...cellSx, fontWeight: 700, textAlign: "center" }}>
                {formatPct(row.qualifying_score)}
              </TableCell>
              {tfMode
                ? TF_COLUMNS.map((col, index) => (
                    <TableCell
                      key={col.key}
                      sx={{
                        ...(index === 0 ? psvCellSx : psvFollowSx),
                        color: col.color,
                        fontWeight: 700,
                      }}
                    >
                      <PsvDiagram score={row[col.key] as number | null | undefined} color={col.color} />
                    </TableCell>
                  ))
                : (
                    <>
                      <TableCell sx={{ ...psvCellSx, color: "#3ecf8e", fontWeight: 700 }}>
                        <PsvDiagram score={row.product} color="#3ecf8e" />
                      </TableCell>
                      <TableCell sx={{ ...psvFollowSx, color: "#4ea1ff", fontWeight: 700 }}>
                        <PsvDiagram score={row.shop} color="#4ea1ff" />
                      </TableCell>
                      <TableCell sx={{ ...psvFollowSx, color: "#ff7eb6", fontWeight: 700 }}>
                        <PsvDiagram score={row.voucher} color="#ff7eb6" />
                      </TableCell>
                    </>
                  )}
              <TableCell sx={{ ...cellSx, textAlign: "center" }}>
                <SubmittedTime value={row.submitted_at} />
              </TableCell>
              <TableCell sx={{ ...cellSx, fontWeight: 700, textAlign: "center" }}>
                {(() => {
                  const label = formatInt(row.race_count);
                  const races = formatRaceList(row.races);
                  if (!races.length) {
                    return label;
                  }
                  return (
                    <Tooltip
                      arrow
                      placement="bottom"
                      title={
                        <Box
                          sx={{
                            color: "#ffffff",
                            fontSize: "0.82rem",
                            fontWeight: 600,
                            lineHeight: 1.55,
                            letterSpacing: "0.02em",
                          }}
                        >
                          {races.join(", ")}
                        </Box>
                      }
                      slotProps={{
                        tooltip: {
                          sx: {
                            px: 1.15,
                            py: 0.7,
                            backgroundColor: "#1c232c",
                            border: "1px solid #3d4654",
                            color: "#ffffff",
                            boxShadow: "0 6px 18px rgba(0,0,0,0.45)",
                          },
                        },
                        arrow: { sx: { color: "#1c232c" } },
                      }}
                    >
                      <Box component="span" sx={{ cursor: "default" }}>
                        {label}
                      </Box>
                    </Tooltip>
                  );
                })()}
              </TableCell>
              <TableCell sx={{ ...cellSx, textAlign: "center" }}>
                <SparkLine
                  points={row.races ?? row.o_trend}
                  scoreKey="o"
                  onOpen={() =>
                    setTrendOpen({
                      name: row.agent_name,
                      version: row.version_number,
                      tab: "o",
                      ...raceRange(row.races ?? row.o_trend),
                      points: row.races ?? row.o_trend ?? [],
                    })
                  }
                />
              </TableCell>
              <TableCell sx={{ ...cellSx, textAlign: "center" }}>
                <SparkLine
                  points={row.races ?? row.r_trend}
                  scoreKey="r"
                  onOpen={() =>
                    setTrendOpen({
                      name: row.agent_name,
                      version: row.version_number,
                      tab: "r",
                      ...raceRange(row.races ?? row.r_trend),
                      points: row.races ?? row.r_trend ?? [],
                    })
                  }
                />
              </TableCell>
              {showGroup ? <TableCell sx={cellSx}>{row.group || "-"}</TableCell> : null}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
    {trendOpen ? (
      <TrendDialog
        name={trendOpen.name}
        version={trendOpen.version}
        tab={trendOpen.tab}
        first={trendOpen.first}
        last={trendOpen.last}
        points={trendOpen.points}
        scoreMode={scoreMode}
        onClose={() => setTrendOpen(null)}
      />
    ) : null}
    </>
  );
}
