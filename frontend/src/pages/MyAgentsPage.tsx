import { useEffect, useMemo, useState } from "react";
import Check from "@mui/icons-material/Check";
import ContentCopy from "@mui/icons-material/ContentCopy";
import PushPin from "@mui/icons-material/PushPin";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import CircularProgress from "@mui/material/CircularProgress";
import Snackbar from "@mui/material/Snackbar";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";

import { CopyMark, submitCommand } from "../CopyMark";
import { fetchCurrentOro, fetchMyAgents, pinAgent, type MyAgent } from "../api";
import { availableAgentCount, availableHotkeyCounts } from "../availableAgents";
import { applyHotkeyCooldowns, subscribeHotkeyCooldowns } from "../hotkeyCooldown";

const mono =
  'ui-monospace, "SFMono-Regular", "Cascadia Mono", "Roboto Mono", Menlo, Consolas, monospace';

const GREEN = "#3ecf8e";
const PINK = "#f472b6";
const RED = "#e85d75";
const ROW_BG = "#12171d";
const ROW_BG_ALT = "#1a2028";
const ROW_HOVER = "#1c2535";

const cellSx = {
  color: "#c5c9d0",
  borderColor: "#232830",
  backgroundColor: "#12171d",
  fontSize: "0.9rem",
  py: 0.85,
  px: 1,
  whiteSpace: "nowrap",
  textAlign: "center",
  overflow: "hidden",
  textOverflow: "ellipsis",
} as const;

const CMD_COL_WIDTH = 44;

const cmdColSx = {
  width: CMD_COL_WIDTH,
  minWidth: CMD_COL_WIDTH,
  maxWidth: CMD_COL_WIDTH,
  overflow: "hidden",
  boxSizing: "border-box",
  px: 0.25,
} as const;

const headSx = {
  ...cellSx,
  color: "#7d8590",
  fontWeight: 600,
  fontSize: "0.8rem",
  letterSpacing: "0.04em",
  py: 1,
  position: "sticky",
  top: 0,
  zIndex: 3,
  backgroundColor: "#12171d",
} as const;

const tableScrollSx = {
  flex: 1,
  minHeight: 0,
  overflow: "auto",
  backgroundColor: "#12171d",
  border: "1px solid #2a3038",
  borderRadius: "8px",
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
} as const;

function formatMargin(value: number | null): string {
  if (value == null) {
    return "-";
  }
  if (value === 0) {
    return "";
  }
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}`;
}

function marginColor(value: number | null): string {
  if (value == null) {
    return "#7d8590";
  }
  return value >= 0 ? GREEN : "#e85d75";
}

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

function isCurrentAgent(row: MyAgent, status: string): boolean {
  if (row.pinned || row.in_current_race || row.is_active_qualifier) {
    return true;
  }
  const raw = (row.status || "").replace(/[_-]/g, " ").toLowerCase();
  const shown = (status || "").replace(/[_-]/g, " ").toLowerCase();
  const first = (shown.split("\n")[0] || raw.split("\n")[0] || "").trim();
  if (first === "running" || first === "received") {
    return true;
  }
  return (
    (raw.includes("qualifying") && !raw.includes("drop")) ||
    shown.includes("qualifying in")
  );
}

const NEW_AGENT_PIN_AFTER = Date.parse("2026-09-10T00:00:00Z");

function submittedFromNow(row: MyAgent): boolean {
  const stamp = Date.parse(row.submitted_at || "");
  return Number.isFinite(stamp) && stamp >= NEW_AGENT_PIN_AFTER;
}

function isNewAgent(row: MyAgent, status: string): boolean {
  if (isCurrentAgent(row, status)) {
    return false;
  }
  const shown = (status || "").replace(/[_-]/g, " ").toLowerCase();
  const first = (shown.split("\n")[0] || "").trim();
  if (!first || first.includes("drop") || first.includes("eliminat")) {
    return false;
  }
  const queued = first === "queued" || first.startsWith("queued");
  return queued && submittedFromNow(row);
}

function statusColor(value: string): string {
  const state = value.replace(/_/g, " ").toLowerCase();
  if (
    state.includes("eliminated") ||
    state.includes("discarded") ||
    state.includes("cancelled") ||
    submitErrorLabel(value)
  ) {
    return RED;
  }
  if (state.includes("drop")) {
    return "#e89b25";
  }
  if (
    state.includes("qualifying") ||
    state.includes("eligible") ||
    state.includes("running")
  ) {
    return GREEN;
  }
  if (state.includes("queued") || state.includes("received")) {
    return "#e89b25";
  }
  return "#c5c9d0";
}

function formatPct(value: number | null): string {
  if (value == null) {
    return "-";
  }
  return `${(value * 100).toFixed(1)}%`;
}

function SubmittedTime({ value }: { value: string | null }) {
  if (!value) {
    return <Box component="span">-</Box>;
  }
  const text = value.trim();
  const stamp = /[zZ]|[+-]\d{2}:\d{2}$/.test(text)
    ? Date.parse(text)
    : Date.parse(`${text.includes("T") ? text : text.replace(" ", "T")}Z`);
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
    <Box sx={{ display: "flex", flexDirection: "column", alignItems: "center", lineHeight: 1.25 }}>
      <Box>{`${get("year")}-${get("month")}-${get("day")}`}</Box>
      <Box>{`${get("hour")}:${get("minute")}:${get("second")} JST`}</Box>
    </Box>
  );
}

function formatCooldown(endsAt: string | null, now: number): string {
  if (!endsAt) {
    return "-";
  }
  const text = endsAt.trim();
  const stamp = /[zZ]|[+-]\d{2}:\d{2}$/.test(text)
    ? Date.parse(text)
    : Date.parse(`${text.includes("T") ? text : text.replace(" ", "T")}Z`);
  const left = Math.floor((stamp - now) / 1000);
  if (!Number.isFinite(left) || left <= 0) {
    return "-";
  }
  const hours = Math.floor(left / 3600);
  const minutes = Math.floor((left % 3600) / 60);
  const seconds = left % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function shortKey(value: string): string {
  if (value.length <= 12) {
    return value || "—";
  }
  return `${value.slice(0, 5)}…${value.slice(-5)}`;
}

function CopyableKey({ value, color }: { value: string; color?: string }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    if (!value) {
      return;
    }
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      const area = document.createElement("textarea");
      area.value = value;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.left = "-9999px";
      document.body.appendChild(area);
      area.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(area);
      if (!ok) {
        return;
      }
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  };

  return (
    <Box sx={{ display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 0.6 }}>
      <Box component="span" title={value} sx={{ fontFamily: mono, color: color || "inherit" }}>
        {shortKey(value)}
      </Box>
      {value ? (
        <Tooltip
          title="Copied"
          open={copied}
          placement="top"
          arrow
          disableHoverListener
          disableFocusListener
          disableTouchListener
        >
          <Box
            component="button"
            type="button"
            onClick={() => {
              void copy();
            }}
            sx={{
              display: "inline-flex",
              alignItems: "center",
              border: 0,
              background: "none",
              p: 0,
              color: copied ? "#4ea1ff" : "#8a8f98",
              cursor: "pointer",
              "&:hover": { color: copied ? "#4ea1ff" : "#c5c9d0" },
            }}
          >
            {copied ? <Check sx={{ fontSize: 14 }} /> : <ContentCopy sx={{ fontSize: 14 }} />}
          </Box>
        </Tooltip>
      ) : null}
    </Box>
  );
}

export default function MyAgentsPage() {
  const [rows, setRows] = useState<MyAgent[]>([]);
  const [loading, setLoading] = useState(true);
  const [now, setNow] = useState(() => Date.now());
  const [raceNumber, setRaceNumber] = useState<number | null>(null);
  const [raceStatus, setRaceStatus] = useState<string | null>(null);
  const [qualifyingThreshold, setQualifyingThreshold] = useState<number | null>(null);
  const [pinningId, setPinningId] = useState<string | null>(null);
  const [pinError, setPinError] = useState<string | null>(null);

  const queuedStatus = (row: MyAgent) => {
    if (row.eliminated_in_race_number != null || /eliminated/i.test(row.status || "")) {
      return row.status;
    }
    if (row.status && submitErrorLabel(row.status)) {
      return row.status;
    }
    const fromText = (row.status || "").match(/#\s*(\d+)/)?.[1];
    const race = raceNumber != null ? String(raceNumber) : fromText;
    return race ? `Qualifying In\nRace #${race}` : "Qualifying In";
  };

  const applyPinSuccess = (versionId: string, hotkey: string) => {
    setRows((current) =>
      current.map((row) => {
        if ((row.miner_hotkey || "") !== hotkey) {
          return row;
        }
        if (row.agent_version_id === versionId) {
          return {
            ...row,
            pinned: true,
            pinnable: false,
            is_active_qualifier: true,
            status: queuedStatus(row),
          };
        }
        if (row.pinned || row.is_active_qualifier) {
          return {
            ...row,
            pinned: false,
            pinnable: true,
            is_active_qualifier: false,
            status: /queued|qualifying in/i.test(row.status || "") ? "Queued" : row.status,
          };
        }
        return row;
      }),
    );
  };

  const handlePin = (row: MyAgent) => {
    if (!row.pinnable || pinningId || !row.agent_version_id || !row.miner_hotkey) {
      return;
    }
    const versionId = row.agent_version_id;
    const hotkey = row.miner_hotkey;
    setPinningId(versionId);
    void pinAgent(versionId, hotkey).then((result) => {
      if (result.ok) {
        applyPinSuccess(versionId, hotkey);
      } else {
        setPinError(result.error || "pin failed");
      }
      setPinningId(null);
    });
  };

  useEffect(() => {
    const tick = window.setInterval(() => {
      setNow(Date.now());
    }, 1_000);
    return () => {
      window.clearInterval(tick);
    };
  }, []);

  useEffect(() => {
    return subscribeHotkeyCooldowns((hotkey, endsAt) => {
      setRows((current) =>
        applyHotkeyCooldowns(
          current.map((row) =>
            row.miner_hotkey === hotkey ? { ...row, cooldown_ends_at: endsAt } : row,
          ),
        ),
      );
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      const first = await fetchMyAgents();
      if (cancelled) {
        return;
      }
      setRows(applyHotkeyCooldowns(first.rows));
      if (first.complete === false) {
        const next = await fetchMyAgents();
        if (cancelled) {
          return;
        }
        setRows(applyHotkeyCooldowns(next.rows));
      }
      setLoading(false);
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      const oro = await fetchCurrentOro();
      if (cancelled || !oro) {
        return;
      }
      setRaceNumber(oro.race_number);
      setRaceStatus(oro.race_status);
      setQualifyingThreshold(oro.qualifying_threshold);
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const sortedRows = useMemo(() => {
    const submittedAt = (row: MyAgent) => {
      const text = (row.submitted_at || "").trim();
      if (!text) {
        return 0;
      }
      const stamp = /[zZ]|[+-]\d{2}:\d{2}$/.test(text)
        ? Date.parse(text)
        : Date.parse(`${text.includes("T") ? text : text.replace(" ", "T")}Z`);
      return Number.isFinite(stamp) ? stamp : 0;
    };
    const groups: MyAgent[][] = [];
    const indexByHot = new Map<string, number>();
    for (const row of rows) {
      const key = row.miner_hotkey || "";
      let index = indexByHot.get(key);
      if (index == null) {
        index = groups.length;
        indexByHot.set(key, index);
        groups.push([]);
      }
      groups[index].push(row);
    }
    return groups.flatMap((group) =>
      [...group].sort((a, b) => {
        const bySubmitted = submittedAt(b) - submittedAt(a);
        if (bySubmitted !== 0) {
          return bySubmitted;
        }
        return (b.version_number || 0) - (a.version_number || 0);
      }),
    );
  }, [rows]);

  const rowShade = useMemo(() => {
    const shade = new Map<string, string>();
    let alt = false;
    let previous = "";
    for (const row of sortedRows) {
      const key = row.miner_hotkey || row.hotkey_name || "";
      if (key !== previous) {
        if (previous) {
          alt = !alt;
        }
        previous = key;
        shade.set(key, alt ? ROW_BG_ALT : ROW_BG);
      }
    }
    return shade;
  }, [sortedRows]);

  const firstOfHotkey = useMemo(() => {
    const first = new Set<string>();
    const seen = new Set<string>();
    for (const row of sortedRows) {
      const key = row.miner_hotkey || row.hotkey_name || "";
      if (!seen.has(key)) {
        seen.add(key);
        first.add(row.agent_version_id || key);
      }
    }
    return first;
  }, [sortedRows]);

  const raceStatusText = (raceStatus || "").replace(/_/g, " ").toLowerCase();
  const raceRunning = raceStatusText === "race running";
  const hotkeyCounts = useMemo(
    () => availableHotkeyCounts(sortedRows, now),
    [now, sortedRows],
  );

  const agentCount = useMemo(
    () => availableAgentCount(sortedRows, qualifyingThreshold, raceNumber),
    [qualifyingThreshold, raceNumber, sortedRows],
  );

  const countChipSx = {
    display: "inline-flex",
    alignItems: "center",
    gap: 0.75,
    px: 1.75,
    py: 0.85,
    flexShrink: 0,
    borderRadius: 999,
    fontSize: "1.15rem",
    fontWeight: 500,
    lineHeight: 1,
    whiteSpace: "nowrap",
  } as const;

  return (
    <Box
      sx={{
        height: "100%",
        overflow: "hidden",
        p: { xs: 1.5, md: 2 },
        display: "flex",
        flexDirection: "column",
        minHeight: 0,
      }}
    >
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 1.25,
          mb: 1.5,
        }}
      >
        <Box sx={{ display: "flex", alignItems: "center", gap: 1.25, ml: 1.5, minWidth: 0 }}>
          <Box sx={{ ...countChipSx, backgroundColor: "#301624", color: PINK }}>
            Agent:{" "}
            <Box component="span" sx={{ fontWeight: 700 }}>
              {agentCount}
            </Box>
          </Box>
          <Box sx={{ ...countChipSx, backgroundColor: "#163028", color: GREEN }}>
            Hotkey:{" "}
            <Box component="span" sx={{ fontWeight: 700 }}>
              {hotkeyCounts.ready}/{hotkeyCounts.total}
            </Box>
          </Box>
        </Box>
        <Box
          sx={{
            display: "flex",
            alignItems: "center",
            gap: 1.25,
            flexShrink: 0,
          }}
        >
        <Box
          sx={{
            display: "inline-flex",
            alignItems: "center",
            gap: 0.5,
            px: 0.9,
            py: "3px",
            flexShrink: 0,
            borderRadius: "6px",
            backgroundColor: "#1c2128",
            border: "1px solid #30363d",
            fontFamily: mono,
            fontSize: "0.7rem",
            lineHeight: 1.2,
            whiteSpace: "nowrap",
          }}
        >
          <Box component="span" sx={{ color: "#c5c9d0" }}>
            Current
          </Box>
          <Box component="span" sx={{ color: "#e3a028", fontWeight: 700 }}>
            #{raceNumber ?? "—"}
          </Box>
        </Box>
        <Box
          sx={{
            display: "inline-flex",
            alignItems: "center",
            gap: 0.75,
            height: 22,
            px: 1,
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
              fontSize: "0.7rem",
              fontWeight: 500,
              lineHeight: 1,
              whiteSpace: "nowrap",
            }}
          >
            {raceStatus ? raceStatus.replace(/_/g, " ").toLowerCase() : "—"}
          </Typography>
        </Box>
        </Box>
      </Box>
      <TableContainer sx={tableScrollSx}>
        <Table
          sx={{
            backgroundColor: "#12171d",
            width: "100%",
            tableLayout: "fixed",
          }}
        >
          <TableHead>
            <TableRow>
              <TableCell sx={headSx}>#</TableCell>
              <TableCell sx={{ ...headSx, ...cmdColSx, overflow: "visible" }}>CMD</TableCell>
              <TableCell sx={headSx}>AGENT</TableCell>
              <TableCell sx={{ ...headSx, textAlign: "center" }}>Pin</TableCell>
              <TableCell sx={{ ...headSx, textAlign: "center" }}>Status</TableCell>
              <TableCell sx={headSx}>Q</TableCell>
              <TableCell sx={headSx}>R</TableCell>
              <TableCell sx={headSx}>Margin</TableCell>
              <TableCell sx={headSx}>UID</TableCell>
              <TableCell sx={headSx}>Hotkey name</TableCell>
              <TableCell sx={headSx}>Hotkey</TableCell>
              <TableCell sx={headSx}>Coldkey</TableCell>
              <TableCell sx={headSx}>Submitted</TableCell>
              <TableCell sx={headSx}>Next time</TableCell>
              <TableCell sx={headSx}>Cooldown</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={15} sx={{ ...cellSx, py: 6, textAlign: "center", color: "#e89b25" }}>
                  <Box sx={{ display: "inline-flex", alignItems: "center", gap: 1.25 }}>
                    <CircularProgress size={16} sx={{ color: "#e89b25" }} />
                    Loading
                  </Box>
                </TableCell>
              </TableRow>
            ) : !sortedRows.length ? (
              <TableRow>
                <TableCell colSpan={15} sx={{ ...cellSx, color: "#8a8f98" }}>
                  Add a coldkey on My Keys. Never-registered wallet hotkeys stay hidden.
                </TableCell>
              </TableRow>
            ) : (
              sortedRows.map((row, index) => {
                const bg = rowShade.get(row.miner_hotkey || row.hotkey_name || "") || ROW_BG;
                return (
                <TableRow
                  key={row.agent_version_id || `${row.miner_hotkey}-${index}`}
                  sx={{
                    backgroundColor: bg,
                    "& td": { backgroundColor: bg },
                    "&:hover td": { backgroundColor: ROW_HOVER },
                  }}
                >
                  <TableCell sx={cellSx}>{index + 1}</TableCell>
                  <TableCell sx={{ ...cellSx, ...cmdColSx }}>
                    <CopyMark value={submitCommand(row.agent_name || "", row.hotkey_name || "")} />
                  </TableCell>
                  <TableCell sx={cellSx}>
                    <Box
                      component={row.agent_version_id ? "a" : "span"}
                      href={
                        row.agent_version_id
                          ? `https://oroagents.com/agent/${row.agent_version_id}`
                          : undefined
                      }
                      target={row.agent_version_id ? "_blank" : undefined}
                      rel={row.agent_version_id ? "noopener noreferrer" : undefined}
                      sx={{
                        color: "#ffffff",
                        fontWeight: 700,
                        textDecoration: "none",
                        cursor: row.agent_version_id ? "pointer" : "default",
                        "&:hover": row.agent_version_id
                          ? { color: "#ffffff", textDecoration: "underline" }
                          : undefined,
                      }}
                    >
                      {row.agent_name || "—"}
                    </Box>
                    {row.version_number != null ? (
                      <Box component="span" sx={{ ml: 0.6, color: "#6b717a", fontSize: "0.82rem" }}>
                        v{row.version_number}
                      </Box>
                    ) : null}
                  </TableCell>
                  <TableCell sx={{ ...cellSx, textAlign: "center" }}>
                    {(() => {
                      const status = formatStatus(
                        row.status,
                        row.qualifying_score,
                        qualifyingThreshold,
                        raceNumber,
                        row.eliminated_in_race_number,
                        row.pinned || row.in_current_race,
                      );
                      if (isCurrentAgent(row, status) || !isNewAgent(row, status) || !row.pinnable) {
                        return null;
                      }
                      return (
                        <Box
                          component="button"
                          type="button"
                          disabled={pinningId != null}
                          onClick={(event) => {
                            event.preventDefault();
                            event.stopPropagation();
                            handlePin(row);
                          }}
                          sx={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 0.4,
                            px: 0.85,
                            py: 0.55,
                            m: 0,
                            appearance: "none",
                            fontFamily: "inherit",
                            borderRadius: "6px",
                            border: "1px solid #22c55e",
                            backgroundColor: "transparent",
                            color: "#22c55e",
                            fontSize: "0.72rem",
                            fontWeight: 700,
                            lineHeight: 1.2,
                            whiteSpace: "nowrap",
                            cursor: pinningId ? "wait" : "pointer",
                            opacity: pinningId && pinningId !== row.agent_version_id ? 0.55 : 1,
                            "&:hover": {
                              backgroundColor: "rgba(34, 197, 94, 0.12)",
                            },
                            "&:disabled": {
                              cursor: "wait",
                            },
                          }}
                        >
                          <PushPin sx={{ fontSize: 16 }} />
                          Pin
                        </Box>
                      );
                    })()}
                  </TableCell>
                  <TableCell sx={{ ...cellSx, textAlign: "center" }}>
                    {(() => {
                      const status = formatStatus(
                        row.status,
                        row.qualifying_score,
                        qualifyingThreshold,
                        raceNumber,
                        row.eliminated_in_race_number,
                        row.pinned || row.in_current_race,
                      );
                      return status ? (
                        <Box
                          component="span"
                          sx={{
                            color: statusColor(status),
                            fontWeight: 600,
                            fontSize: "0.8rem",
                            lineHeight: 1.25,
                            display: "flex",
                            flexDirection: "column",
                            alignItems: "center",
                            textAlign: "center",
                          }}
                        >
                          {status.split("\n").map((line) => (
                            <Box key={line} component="span" sx={{ whiteSpace: "nowrap" }}>
                              {line}
                            </Box>
                          ))}
                        </Box>
                      ) : (
                        "—"
                      );
                    })()}
                  </TableCell>
                  <TableCell sx={cellSx}>{formatPct(row.qualifying_score)}</TableCell>
                  <TableCell sx={{ ...cellSx, color: GREEN }}>{formatPct(row.race_score)}</TableCell>
                  <TableCell
                    sx={{
                      ...cellSx,
                      color: marginColor(row.margin),
                      fontWeight: 600,
                    }}
                  >
                    {formatMargin(row.margin)}
                  </TableCell>
                  <TableCell sx={{ ...cellSx, fontFamily: mono }}>
                    {row.uid ?? "—"}
                  </TableCell>
                  <TableCell sx={cellSx}>
                    <Box
                      component="span"
                      sx={{ color: row.deregistered ? RED : GREEN, fontWeight: row.deregistered ? 400 : 600 }}
                    >
                      {row.hotkey_name || "-"}
                    </Box>
                  </TableCell>
                  <TableCell sx={{ ...cellSx, fontSize: "0.75rem" }}>
                    <CopyableKey value={row.miner_hotkey} />
                  </TableCell>
                  <TableCell sx={{ ...cellSx, fontSize: "0.75rem" }}>
                    <CopyableKey value={row.coldkey} />
                  </TableCell>
                  <TableCell sx={{ ...cellSx, fontFamily: mono, fontSize: "0.75rem" }}>
                    <SubmittedTime value={row.submitted_at} />
                  </TableCell>
                  <TableCell
                    sx={{
                      ...cellSx,
                      fontFamily: mono,
                      fontSize: "0.75rem",
                      color:
                        !row.deregistered &&
                        firstOfHotkey.has(row.agent_version_id || row.miner_hotkey || row.hotkey_name || "") &&
                        formatCooldown(row.cooldown_ends_at, now) === "-"
                          ? GREEN
                          : cellSx.color,
                    }}
                  >
                    {!row.deregistered &&
                    firstOfHotkey.has(row.agent_version_id || row.miner_hotkey || row.hotkey_name || "")
                      ? <SubmittedTime value={row.cooldown_ends_at} />
                      : ""}
                  </TableCell>
                  <TableCell sx={{ ...cellSx, fontFamily: mono }}>
                    {!row.deregistered &&
                    firstOfHotkey.has(row.agent_version_id || row.miner_hotkey || row.hotkey_name || "") ? (
                      formatCooldown(row.cooldown_ends_at, now) === "-" ? (
                        <Box component="span" sx={{ color: GREEN, fontWeight: 600 }}>
                          Ready
                        </Box>
                      ) : (
                        <Box component="span" sx={{ color: "#f5d76e", fontWeight: 600 }}>
                          {formatCooldown(row.cooldown_ends_at, now)}
                        </Box>
                      )
                    ) : (
                      ""
                    )}
                  </TableCell>
                </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </TableContainer>
      <Snackbar
        open={Boolean(pinError)}
        autoHideDuration={6000}
        onClose={() => {
          setPinError(null);
        }}
        anchorOrigin={{ vertical: "top", horizontal: "right" }}
      >
        <Alert
          severity="error"
          variant="filled"
          onClose={() => {
            setPinError(null);
          }}
          sx={{ backgroundColor: "#e85d75", color: "#ffffff" }}
        >
          {pinError}
        </Alert>
      </Snackbar>
    </Box>
  );
}
