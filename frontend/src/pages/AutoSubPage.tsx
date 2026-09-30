import { useEffect, useMemo, useRef, useState } from "react";
import FileUpload from "@mui/icons-material/FileUpload";
import Pause from "@mui/icons-material/Pause";
import PlayArrow from "@mui/icons-material/PlayArrow";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import CircularProgress from "@mui/material/CircularProgress";
import IconButton from "@mui/material/IconButton";
import Snackbar from "@mui/material/Snackbar";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";

import { CopyMark, submitCommand } from "../CopyMark";
import { fetchMyAgents, submitAutoSub, type MyAgent } from "../api";
import { availableHotkeyCounts } from "../availableAgents";
import { applyHotkeyCooldowns, rememberHotkeyCooldown, subscribeHotkeyCooldowns } from "../hotkeyCooldown";

const GREEN = "#3ecf8e";
const PINK = "#f472b6";
const YELLOW = "#f5d76e";
const ROW_BG = "#12171d";
const ROW_HOVER = "#1c2535";
const ROW_ACTIVE = "#163028";
const ROW_ACTIVE_HOVER = "#1c4034";
const mono =
  'ui-monospace, "SFMono-Regular", "Cascadia Mono", "Roboto Mono", Menlo, Consolas, monospace';

const NOTE_COL_WIDTH = 260;
const AGENT_COL_WIDTH = 130;
const CODE_COL_WIDTH = 180;
const CMD_COL_WIDTH = 44;
const NO_COL_WIDTH = 36;

const noColSx = {
  width: `${NO_COL_WIDTH}px !important`,
  minWidth: `${NO_COL_WIDTH}px !important`,
  maxWidth: `${NO_COL_WIDTH}px !important`,
  paddingLeft: "4px !important",
  paddingRight: "4px !important",
  boxSizing: "border-box",
} as const;

const cmdColSx = {
  width: `${CMD_COL_WIDTH}px !important`,
  minWidth: `${CMD_COL_WIDTH}px !important`,
  maxWidth: `${CMD_COL_WIDTH}px !important`,
  overflow: "hidden",
  boxSizing: "border-box",
  px: 0,
} as const;

function fixedColSx(width: number) {
  return {
    width,
    minWidth: width,
    maxWidth: width,
    overflow: "hidden",
    boxSizing: "border-box",
  } as const;
}

function fixedInnerSx(width: number) {
  return {
    width: "100%",
    maxWidth: "100%",
    minWidth: 0,
    overflow: "hidden",
    boxSizing: "border-box",
  } as const;
}

const agentColSx = fixedColSx(AGENT_COL_WIDTH);
const codeColSx = fixedColSx(CODE_COL_WIDTH);
const noteColSx = fixedColSx(NOTE_COL_WIDTH);

const hotkeyColSx = {
  whiteSpace: "nowrap",
  pl: 0.25,
  pr: 1,
} as const;

const cellSx = {
  color: "#c5c9d0",
  borderColor: "#232830",
  fontSize: "0.9rem",
  py: 0.85,
  px: 1,
  whiteSpace: "nowrap",
  textAlign: "center",
  overflow: "hidden",
  textOverflow: "ellipsis",
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

const PLAYING_KEY = "oro-auto-sub-playing";

function readPlaying(): Record<string, boolean> {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(PLAYING_KEY) || "{}") as unknown;
    if (!parsed || typeof parsed !== "object") {
      return {};
    }
    return Object.fromEntries(
      Object.entries(parsed as Record<string, unknown>).filter(([, on]) => on === true),
    ) as Record<string, boolean>;
  } catch {
    return {};
  }
}

function writePlaying(value: Record<string, boolean>) {
  const on = Object.fromEntries(Object.entries(value).filter(([, playing]) => playing));
  try {
    window.localStorage.setItem(PLAYING_KEY, JSON.stringify(on));
  } catch {
    /* ignore quota */
  }
}

type Slot = {
  id: string;
  label: string;
  agent: MyAgent;
  maxVersion: number | null;
};

function submittedStamp(value: string | null): number {
  if (!value) {
    return 0;
  }
  const text = value.trim();
  const stamp = /[zZ]|[+-]\d{2}:\d{2}$/.test(text)
    ? Date.parse(text)
    : Date.parse(`${text.includes("T") ? text : text.replace(" ", "T")}Z`);
  return Number.isFinite(stamp) ? stamp : 0;
}

function latestByHotkey(rows: MyAgent[]): Slot[] {
  const groups = new Map<string, MyAgent[]>();
  const order: string[] = [];
  for (const row of rows) {
    if (row.deregistered) {
      continue;
    }
    const id = row.miner_hotkey || row.hotkey_name || "";
    if (!id) {
      continue;
    }
    if (!groups.has(id)) {
      groups.set(id, []);
      order.push(id);
    }
    groups.get(id)?.push(row);
  }
  return order.map((id) => {
    const items = [...(groups.get(id) || [])].sort((a, b) => {
      const bySubmitted = submittedStamp(b.submitted_at) - submittedStamp(a.submitted_at);
      if (bySubmitted !== 0) {
        return bySubmitted;
      }
      return (b.version_number || 0) - (a.version_number || 0);
    });
    const agent = items[0];
    const versions = items
      .map((item) => item.version_number)
      .filter((value): value is number => value != null);
    return {
      id,
      label: agent.hotkey_name || id.slice(0, 8),
      agent,
      maxVersion: versions.length ? Math.max(...versions) : agent.version_number,
    };
  });
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
    <Box sx={{ display: "flex", flexDirection: "column", alignItems: "center", lineHeight: 1.25, fontFamily: mono, fontSize: "0.75rem" }}>
      <Box>{`${get("year")}-${get("month")}-${get("day")}`}</Box>
      <Box>{`${get("hour")}:${get("minute")}:${get("second")} JST`}</Box>
    </Box>
  );
}

type AutoSubStatus = "-" | "Success" | "FAIL";

type AutoSubState = {
  status: AutoSubStatus;
  submittedAt: string | null;
  note: string;
};

function formatJstNote(value: string | null): string {
  if (!value) {
    return "";
  }
  const text = value.trim();
  const stamp = /[zZ]|[+-]\d{2}:\d{2}$/.test(text)
    ? Date.parse(text)
    : Date.parse(`${text.includes("T") ? text : text.replace(" ", "T")}Z`);
  if (!Number.isFinite(stamp)) {
    return value;
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
  return `${get("year")}-${get("month")}-${get("day")} ${get("hour")}:${get("minute")}:${get("second")} JST`;
}

function cooldownReady(endsAt: string | null, now: number): boolean {
  return formatCooldown(endsAt, now) === "-";
}

function autoSubColor(value: AutoSubStatus): string {
  if (value === "FAIL") {
    return "#e85d75";
  }
  if (value === "Success") {
    return GREEN;
  }
  return "#8a8f98";
}

export default function AutoSubPage() {
  const [rows, setRows] = useState<MyAgent[]>([]);
  const [loading, setLoading] = useState(true);
  const [now, setNow] = useState(() => Date.now());
  const [agentNames, setAgentNames] = useState<Record<string, string>>({});
  const [playing, setPlaying] = useState<Record<string, boolean>>(readPlaying);
  const [codeFiles, setCodeFiles] = useState<Record<string, File | null>>({});
  const [notice, setNotice] = useState<{ text: string; kind: "success" | "error" } | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [autoSubs, setAutoSubs] = useState<Record<string, AutoSubState>>({});
  const submittingRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    writePlaying(playing);
  }, [playing]);

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

  const hotkeyCounts = useMemo(() => availableHotkeyCounts(rows, now), [now, rows]);
  const slots = useMemo(() => latestByHotkey(rows), [rows]);

  useEffect(() => {
    setAgentNames((current) => {
      const next = { ...current };
      for (const slot of slots) {
        if (next[slot.id] == null) {
          next[slot.id] = slot.agent.agent_name || "";
        }
      }
      return next;
    });
  }, [slots]);

  useEffect(() => {
    const dereged = slots.filter((slot) => playing[slot.id] && slot.agent.deregistered);
    if (dereged.length) {
      setNotice({ text: "dereged", kind: "error" });
      setPlaying((current) => {
        const next = { ...current };
        for (const slot of dereged) {
          next[slot.id] = false;
        }
        return next;
      });
      setAutoSubs((current) => {
        const next = { ...current };
        for (const slot of dereged) {
          next[slot.id] = {
            status: "FAIL",
            submittedAt: current[slot.id]?.submittedAt ?? null,
            note: "dereged",
          };
        }
        return next;
      });
    }
    const ready = slots.filter((slot) => {
      if (!playing[slot.id] || submittingRef.current.has(slot.id) || slot.agent.deregistered) {
        return false;
      }
      if (!codeFiles[slot.id]) {
        return false;
      }
      return cooldownReady(slot.agent.cooldown_ends_at, now);
    });
    if (!ready.length) {
      return;
    }
    for (const slot of ready) {
      submittingRef.current.add(slot.id);
      const file = codeFiles[slot.id];
      const agentName = (agentNames[slot.id] ?? slot.agent.agent_name ?? "").trim();
      if (!file) {
        submittingRef.current.delete(slot.id);
        continue;
      }
      void submitAutoSub({
        hotkey: slot.id,
        agentName,
        file,
      }).then((result) => {
        const submittedAt = result.submitted_at || new Date().toISOString();
        const note =
          result.status === "Success"
            ? formatJstNote(result.next_allowed_at) || formatJstNote(submittedAt)
            : result.reason || "submit-failed";
        setAutoSubs((current) => ({
          ...current,
          [slot.id]: {
            status: result.status,
            submittedAt,
            note,
          },
        }));
        setPlaying((current) => ({ ...current, [slot.id]: false }));
        submittingRef.current.delete(slot.id);
        if (result.next_allowed_at) {
          rememberHotkeyCooldown(slot.id, result.next_allowed_at);
          setRows((current) =>
            applyHotkeyCooldowns(
              current.map((row) =>
                row.miner_hotkey === slot.id
                  ? { ...row, cooldown_ends_at: result.next_allowed_at }
                  : row,
              ),
            ),
          );
        }
        if (result.ok) {
          void fetchMyAgents().then((payload) => {
            setRows(applyHotkeyCooldowns(payload.rows));
          });
        }
      });
    }
  }, [agentNames, codeFiles, now, playing, slots]);

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
      <Box sx={{ display: "flex", alignItems: "center", ml: 1.5, mb: 1.5 }}>
        <Box
          sx={{
            display: "inline-flex",
            alignItems: "center",
            gap: 0.75,
            px: 1.75,
            py: 0.85,
            flexShrink: 0,
            borderRadius: 999,
            backgroundColor: "#163028",
            color: GREEN,
            fontSize: "1.15rem",
            fontWeight: 500,
            lineHeight: 1,
            whiteSpace: "nowrap",
          }}
        >
          Hotkey:{" "}
          <Box component="span" sx={{ fontWeight: 700 }}>
            {hotkeyCounts.ready}/{hotkeyCounts.total}
          </Box>
        </Box>
      </Box>
      <TableContainer sx={tableScrollSx}>
        <Table
          sx={{
            backgroundColor: "#12171d",
            width: "100%",
            tableLayout: "fixed",
            borderCollapse: "separate",
            borderSpacing: 0,
            "& col.oro-no": {
              width: NO_COL_WIDTH,
            },
            "& col.oro-cmd": {
              width: CMD_COL_WIDTH,
            },
            "& th:nth-of-type(2), & td:nth-of-type(2)": {
              width: `${CMD_COL_WIDTH}px !important`,
              minWidth: `${CMD_COL_WIDTH}px !important`,
              maxWidth: `${CMD_COL_WIDTH}px !important`,
            },
          }}
        >
          <colgroup>
            <col className="oro-no" style={{ width: NO_COL_WIDTH }} />
            <col className="oro-cmd" style={{ width: CMD_COL_WIDTH }} />
            <col />
            <col style={{ width: AGENT_COL_WIDTH }} />
            <col style={{ width: CODE_COL_WIDTH }} />
            <col />
            <col />
            <col />
            <col />
            <col />
            <col style={{ width: NOTE_COL_WIDTH }} />
            <col />
          </colgroup>
          <TableHead>
            <TableRow>
              <TableCell sx={{ ...headSx, ...noColSx }}>No</TableCell>
              <TableCell sx={{ ...headSx, ...cmdColSx, letterSpacing: 0, overflow: "visible", textOverflow: "clip" }}>
                CMD
              </TableCell>
              <TableCell sx={{ ...headSx, ...hotkeyColSx }}>Hotkey</TableCell>
              <TableCell sx={{ ...headSx, ...agentColSx }}>Agent</TableCell>
              <TableCell sx={{ ...headSx, ...codeColSx }}>Code</TableCell>
              <TableCell sx={headSx}>Version</TableCell>
              <TableCell sx={headSx}>Cooldown</TableCell>
              <TableCell sx={headSx}>Status</TableCell>
              <TableCell sx={headSx}>Submitted</TableCell>
              <TableCell sx={headSx}>Response</TableCell>
              <TableCell sx={{ ...headSx, ...noteColSx }}>Note</TableCell>
              <TableCell sx={headSx} />
            </TableRow>
          </TableHead>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={12} sx={{ ...cellSx, py: 6, textAlign: "center", color: "#e89b25" }}>
                  <Box sx={{ display: "inline-flex", alignItems: "center", gap: 1.25 }}>
                    <CircularProgress size={16} sx={{ color: "#e89b25" }} />
                    Loading
                  </Box>
                </TableCell>
              </TableRow>
            ) : !slots.length ? (
              <TableRow>
                <TableCell colSpan={12} sx={{ ...cellSx, color: "#8a8f98" }}>
                  No available hotkeys.
                </TableCell>
              </TableRow>
            ) : (
              slots.map((slot, index) => {
                const agent = slot.agent;
                const cooldown = formatCooldown(agent.cooldown_ends_at, now);
                const autoSub = autoSubs[slot.id] ?? { status: "-", submittedAt: null, note: "" };
                const running = Boolean(playing[slot.id]);
                const rowBg = running ? ROW_ACTIVE : ROW_BG;
                const rowHover = running ? ROW_ACTIVE_HOVER : ROW_HOVER;
                const rowCellSx = {
                  ...cellSx,
                  ...(running
                    ? {
                        backgroundColor: "transparent",
                      }
                    : { backgroundColor: rowBg }),
                };
                return (
                  <TableRow
                    selected={running}
                    key={`${slot.id}-${index}`}
                    sx={
                      running
                        ? {
                            backgroundColor: ROW_ACTIVE,
                            backgroundImage:
                              "linear-gradient(90deg, #163028 0%, #163028 35%, #1f4a38 50%, #163028 65%, #163028 100%)",
                            backgroundSize: "220% 100%",
                            animation: "oroRowLoop 2.2s linear infinite",
                            "@keyframes oroRowLoop": {
                              "0%": { backgroundPosition: "100% 0" },
                              "100%": { backgroundPosition: "-100% 0" },
                            },
                            "&.Mui-selected": { backgroundColor: ROW_ACTIVE },
                            "& td": {
                              backgroundColor: "transparent",
                              boxShadow: `inset 0 1px 0 ${GREEN}, inset 0 -1px 0 ${GREEN}`,
                            },
                            "& td:first-of-type": {
                              boxShadow: `inset 1px 0 0 ${GREEN}, inset 0 1px 0 ${GREEN}, inset 0 -1px 0 ${GREEN}`,
                            },
                            "& td:last-of-type": {
                              boxShadow: `inset -1px 0 0 ${GREEN}, inset 0 1px 0 ${GREEN}, inset 0 -1px 0 ${GREEN}`,
                            },
                          }
                        : {
                            backgroundColor: rowBg,
                            "& td": { backgroundColor: rowBg },
                            "&:hover td": { backgroundColor: rowHover },
                          }
                    }
                  >
                    <TableCell sx={{ ...rowCellSx, ...noColSx }}>{index + 1}</TableCell>
                    <TableCell sx={{ ...rowCellSx, ...cmdColSx }}>
                      <CopyMark
                        value={submitCommand(
                          agentNames[slot.id] ?? agent.agent_name ?? "",
                          slot.label,
                        )}
                      />
                    </TableCell>
                    <TableCell sx={{ ...rowCellSx, ...hotkeyColSx, color: GREEN, fontWeight: 700, fontSize: "1.05rem" }}>
                      {slot.label}
                    </TableCell>
                    <TableCell sx={{ ...rowCellSx, ...agentColSx }}>
                      <Box sx={{ display: "flex", justifyContent: "center", ...fixedInnerSx(AGENT_COL_WIDTH) }}>
                        <TextField
                          size="small"
                          value={agentNames[slot.id] ?? agent.agent_name ?? ""}
                          onChange={(event) => {
                            const value = event.target.value;
                            setAgentNames((current) => ({ ...current, [slot.id]: value }));
                          }}
                          sx={{
                            width: "100%",
                            minWidth: 0,
                            maxWidth: "100%",
                            "& .MuiOutlinedInput-root": {
                              color: "#d8dce2",
                              fontSize: "0.9rem",
                              fontWeight: 700,
                              backgroundColor: "transparent",
                              "& fieldset": {
                                borderColor: "#2e343c",
                                borderWidth: "1px",
                              },
                              "&:hover fieldset": { borderColor: "#4a5563" },
                              "&.Mui-focused fieldset": {
                                borderColor: "#e89b25",
                                borderWidth: "1px",
                              },
                            },
                            "& .MuiOutlinedInput-input": {
                              py: 0.55,
                              px: 1,
                              textAlign: "center",
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                            },
                          }}
                        />
                      </Box>
                    </TableCell>
                    <TableCell sx={{ ...rowCellSx, ...codeColSx }}>
                      <Box sx={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 0.5, ...fixedInnerSx(CODE_COL_WIDTH) }}>
                        {codeFiles[slot.id] ? (
                          <Box
                            component="span"
                            title={codeFiles[slot.id]?.name}
                            sx={{
                              color: "#c5c9d0",
                              fontSize: "0.78rem",
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                              whiteSpace: "nowrap",
                              minWidth: 0,
                              flex: 1,
                              textAlign: "right",
                            }}
                          >
                            {codeFiles[slot.id]?.name}
                          </Box>
                        ) : null}
                        <IconButton
                          component="label"
                          type="button"
                          size="small"
                          aria-label="Upload code"
                          sx={{
                            color: PINK,
                            p: 0.25,
                            flexShrink: 0,
                            "&:hover": { color: "#f9a8d4", backgroundColor: "rgba(244, 114, 182, 0.08)" },
                          }}
                        >
                          <FileUpload sx={{ fontSize: 20 }} />
                          <input
                            type="file"
                            hidden
                            accept=".py,text/x-python"
                            onChange={(event) => {
                              const file = event.target.files?.[0] ?? null;
                              const python = file && /\.py$/i.test(file.name);
                              setCodeFiles((current) => ({ ...current, [slot.id]: python ? file : current[slot.id] ?? null }));
                              event.target.value = "";
                            }}
                          />
                        </IconButton>
                      </Box>
                    </TableCell>
                    <TableCell sx={rowCellSx}>
                      {agent.version_number != null ? `v${agent.version_number}` : "—"}
                    </TableCell>
                    <TableCell sx={{ ...rowCellSx, fontFamily: mono }}>
                      {cooldown === "-" ? (
                        <Box component="span" sx={{ color: GREEN, fontWeight: 600 }}>
                          Ready
                        </Box>
                      ) : (
                        <Box component="span" sx={{ color: YELLOW, fontWeight: 600 }}>
                          {cooldown}
                        </Box>
                      )}
                    </TableCell>
                    <TableCell sx={rowCellSx}>
                      <Box
                        sx={{
                          color: autoSubColor(autoSub.status),
                          fontWeight: 600,
                          fontSize: "0.8rem",
                          lineHeight: 1.25,
                        }}
                      >
                        {autoSub.status}
                      </Box>
                    </TableCell>
                    <TableCell sx={rowCellSx}>
                      <SubmittedTime value={autoSub.submittedAt} />
                    </TableCell>
                    <TableCell sx={{ ...rowCellSx, color: "#c5c9d0" }}>
                      {autoSub.note ? (
                        <Box
                          component="button"
                          type="button"
                          onClick={() => {
                            setNotice({
                              text: autoSub.note,
                              kind: autoSub.status === "Success" ? "success" : "error",
                            });
                          }}
                          sx={{
                            all: "unset",
                            cursor: "pointer",
                            display: "block",
                            maxWidth: "100%",
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                            color: autoSub.status === "Success" ? GREEN : autoSub.status === "FAIL" ? "#e85d75" : "#c5c9d0",
                          }}
                        >
                          {autoSub.note}
                        </Box>
                      ) : (
                        "—"
                      )}
                    </TableCell>
                    <TableCell sx={{ ...rowCellSx, ...noteColSx }}>
                      <Box sx={{ display: "flex", justifyContent: "center", ...fixedInnerSx(NOTE_COL_WIDTH) }}>
                        <TextField
                          size="small"
                          value={notes[slot.id] || ""}
                          onChange={(event) => {
                            const value = event.target.value;
                            setNotes((current) => ({ ...current, [slot.id]: value }));
                          }}
                          sx={{
                            width: "100%",
                            minWidth: 0,
                            maxWidth: "100%",
                            "& .MuiOutlinedInput-root": {
                              color: "#d8dce2",
                              fontSize: "0.82rem",
                              "& fieldset": {
                                borderColor: "#2e343c",
                                borderWidth: "1px",
                              },
                              "&:hover fieldset": { borderColor: "#4a5563" },
                              "&.Mui-focused fieldset": {
                                borderColor: "#e89b25",
                                borderWidth: "1px",
                              },
                            },
                            "& .MuiOutlinedInput-input": {
                              py: 0.55,
                              px: 1,
                              textAlign: "center",
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                            },
                          }}
                        />
                      </Box>
                    </TableCell>
                    <TableCell sx={rowCellSx}>
                      {running ? (
                        <IconButton
                          type="button"
                          size="small"
                          aria-label="Pause"
                          onClick={() => {
                            setPlaying((current) => ({ ...current, [slot.id]: false }));
                          }}
                          sx={{
                            color: "#4ea1ff",
                            width: 30,
                            height: 30,
                            border: "1.5px solid #4ea1ff",
                            backgroundColor: "rgba(78, 161, 255, 0.22)",
                            "&:hover": { color: "#7bb8ff", borderColor: "#7bb8ff", backgroundColor: "rgba(78, 161, 255, 0.32)" },
                          }}
                        >
                          <Pause sx={{ fontSize: 18 }} />
                        </IconButton>
                      ) : (
                        <IconButton
                          type="button"
                          size="small"
                          aria-label="Play"
                          onClick={() => {
                            if (agent.deregistered) {
                              setNotice({ text: "dereged", kind: "error" });
                              setAutoSubs((current) => ({
                                ...current,
                                [slot.id]: {
                                  status: "FAIL",
                                  submittedAt: current[slot.id]?.submittedAt ?? null,
                                  note: "dereged",
                                },
                              }));
                              return;
                            }
                            if (!codeFiles[slot.id]) {
                              setNotice({ text: "Please upload Agent Code.", kind: "error" });
                              return;
                            }
                            setPlaying((current) => ({ ...current, [slot.id]: true }));
                          }}
                          sx={{
                            color: "#e85d75",
                            width: 30,
                            height: 30,
                            border: "1.5px solid #e85d75",
                            backgroundColor: "transparent",
                            "&:hover": { color: "#f0788c", borderColor: "#f0788c", backgroundColor: "rgba(232, 93, 117, 0.08)" },
                          }}
                        >
                          <PlayArrow sx={{ fontSize: 18 }} />
                        </IconButton>
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
        open={Boolean(notice)}
        autoHideDuration={6000}
        onClose={() => {
          setNotice(null);
        }}
        anchorOrigin={{ vertical: "top", horizontal: "right" }}
      >
        <Alert
          severity={notice?.kind === "success" ? "success" : "error"}
          variant="filled"
          onClose={() => {
            setNotice(null);
          }}
          sx={{
            backgroundColor: notice?.kind === "success" ? GREEN : "#e85d75",
            color: "#ffffff",
            whiteSpace: "pre-wrap",
            maxWidth: 480,
          }}
        >
          {notice?.text}
        </Alert>
      </Snackbar>
    </Box>
  );
}
