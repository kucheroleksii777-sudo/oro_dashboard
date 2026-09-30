import { useEffect, useMemo, useState } from "react";
import Close from "@mui/icons-material/Close";
import Search from "@mui/icons-material/Search";
import Box from "@mui/material/Box";
import CircularProgress from "@mui/material/CircularProgress";
import IconButton from "@mui/material/IconButton";
import InputAdornment from "@mui/material/InputAdornment";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import {
  fetchAgentCode,
  fetchRaceTable,
  fetchRacesList,
  type AgentCodeFile,
  type RaceListItem,
  type SelectedRaceRow,
} from "../api";
import SelectedRaceTable from "./SelectedRaceTable";

const ORANGE = "#e89b25";
const MUTED = "#8a8f98";
const mono =
  'ui-monospace, "SFMono-Regular", "Cascadia Mono", "Roboto Mono", Menlo, Consolas, monospace';

const scrollSx = {
  overflow: "auto",
  scrollbarWidth: "auto",
  scrollbarColor: "#4a5563 transparent",
  "&::-webkit-scrollbar": {
    width: 14,
    height: 14,
  },
  "&::-webkit-scrollbar-track": {
    backgroundColor: "transparent",
    margin: "6px 0",
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
} as const;

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

function RaceMeta({
  race,
  query,
  onQuery,
  publicOnly,
  onPublicOnly,
}: {
  race: RaceListItem | null;
  query: string;
  onQuery: (value: string) => void;
  publicOnly: boolean;
  onPublicOnly: (value: boolean) => void;
}) {
  const when = race ? formatCompleted(race.completed_at) : null;
  const agents = race ? `${race.agent_count.toLocaleString("en-US")} agents` : "";
  return (
    <Box
      sx={{
        display: "flex",
        alignItems: "center",
        gap: 1.5,
        mt: 0.5,
        mb: 1,
        py: 0.25,
      }}
    >
      <Box
        sx={{
          color: MUTED,
          fontSize: "0.75rem",
          fontWeight: 400,
          lineHeight: 1.4,
          minWidth: 0,
          flex: 1,
        }}
      >
        {race ? (when ? `Completed ${when} · ${agents}` : agents) : null}
      </Box>
      <Box
        component="button"
        type="button"
        aria-pressed={publicOnly}
        onMouseDown={(event) => event.preventDefault()}
        onClick={(event) => {
          event.currentTarget.blur();
          onPublicOnly(!publicOnly);
        }}
        sx={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          height: 32,
          px: 0.85,
          flexShrink: 0,
          border: 0,
          boxShadow: publicOnly ? "0 0 0 1px #3ecf8e" : "0 0 0 1px #232830",
          borderRadius: "7px",
          color: publicOnly ? "#3ecf8e" : MUTED,
          backgroundColor: publicOnly ? "#163028" : "#161b22",
          fontSize: "0.75rem",
          fontWeight: 500,
          lineHeight: 1.4,
          cursor: "pointer",
          fontFamily: "inherit",
          outline: "none",
          "&:focus, &:focus-visible, &:active": {
            outline: "none",
            boxShadow: publicOnly ? "0 0 0 1px #3ecf8e" : "0 0 0 1px #232830",
            color: publicOnly ? "#3ecf8e" : MUTED,
            backgroundColor: publicOnly ? "#163028" : "#161b22",
          },
        }}
      >
        public only
      </Box>
      <TextField
        size="small"
        value={query}
        onChange={(event) => onQuery(event.target.value)}
        placeholder="Search agents"
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
                  onClick={() => onQuery("")}
                  sx={{ color: "#8a8f98", p: 0.25, "&:hover": { color: "#c5c9d0" } }}
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
            "& fieldset": { borderColor: "#232830", borderWidth: "1px !important" },
            "&:hover fieldset": { borderColor: "#232830" },
            "&.Mui-focused fieldset": { borderColor: "#e89b25", borderWidth: "1px !important" },
          },
          "& .MuiOutlinedInput-input": {
            py: 0.5,
            "&::placeholder": { color: "#8b949e", opacity: 1 },
          },
        }}
      />
    </Box>
  );
}

function formatPct(value: number | null): string {
  if (value == null) {
    return "-";
  }
  return `${(value * 100).toFixed(1)}%`;
}

function LeaderRow({
  label,
  name,
  score,
  accent,
}: {
  label: string;
  name: string | null;
  score: number | null;
  accent: string;
}) {
  return (
    <Box sx={{ display: "flex", alignItems: "baseline", gap: 1, minWidth: 0 }}>
      <Typography
        sx={{
          color: accent,
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
            {name}
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

function RaceCard({
  race,
  active,
  latest,
  onSelect,
}: {
  race: RaceListItem;
  active: boolean;
  latest: boolean;
  onSelect: () => void;
}) {
  return (
    <Box
      component="button"
      type="button"
      onClick={onSelect}
      sx={{
        display: "block",
        width: "100%",
        flexShrink: 0,
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
        <LeaderRow
          label="Overall"
          name={race.overall_agent}
          score={race.overall_score}
          accent={ORANGE}
        />
        <LeaderRow
          label="Race"
          name={race.race_agent}
          score={race.race_score}
          accent={ORANGE}
        />
      </Box>
    </Box>
  );
}

export default function RacePage() {
  const [races, setRaces] = useState<RaceListItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tableRows, setTableRows] = useState<SelectedRaceRow[]>([]);
  const [tableLoading, setTableLoading] = useState(false);
  const [listLoading, setListLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [publicOnly, setPublicOnly] = useState(false);
  const [codeRow, setCodeRow] = useState<SelectedRaceRow | null>(null);
  const [codeFiles, setCodeFiles] = useState<AgentCodeFile[]>([]);
  const [codeFile, setCodeFile] = useState(0);
  const [codeLoading, setCodeLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      const rows = await fetchRacesList();
      if (cancelled) {
        return;
      }
      const finished = rows.filter((row) => !row.is_latest);
      setRaces(finished);
      setSelectedId((current) => {
        if (current && finished.some((row) => row.race_id === current)) {
          return current;
        }
        return finished[0]?.race_id ?? null;
      });
      setListLoading(false);
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setTableRows([]);
      setTableLoading(false);
      setCodeRow(null);
      return;
    }
    let cancelled = false;
    let followUp = 0;
    setTableLoading(true);
    setTableRows([]);
    setCodeRow(null);
    setQuery("");
    const load = async (initial: boolean) => {
      const data = await fetchRaceTable(selectedId);
      if (cancelled) {
        return;
      }
      if (data) {
        setTableRows(data.rows ?? []);
      }
      if (initial) {
        setTableLoading(false);
      }
    };
    void load(true).then(() => {
      if (cancelled) {
        return;
      }
      followUp = window.setTimeout(() => {
        void load(false);
      }, 3000);
    });
    return () => {
      cancelled = true;
      window.clearTimeout(followUp);
    };
  }, [selectedId]);

  useEffect(() => {
    if (!codeRow) {
      setCodeFiles([]);
      setCodeFile(0);
      setCodeLoading(false);
      return;
    }
    let cancelled = false;
    setCodeLoading(true);
    setCodeFiles([]);
    setCodeFile(0);
    void fetchAgentCode(codeRow.agent_version_id).then((files) => {
      if (cancelled) {
        return;
      }
      setCodeFiles(files);
      setCodeLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [codeRow]);

  const visibleRows = useMemo(() => {
    const text = query.trim().toLowerCase();
    const rows = tableRows.filter((row) => {
      if (publicOnly && row.code !== "public") {
        return false;
      }
      if (!text) {
        return true;
      }
      const name = row.agent_name.toLowerCase();
      const hot = row.miner_hotkey.toLowerCase();
      const cold = (row.coldkey || "").toLowerCase();
      return name.includes(text) || hot.includes(text) || cold.includes(text);
    });
    return [...rows].sort((a, b) => {
      if (a.rank == null && b.rank == null) {
        return 0;
      }
      if (a.rank == null) {
        return 1;
      }
      if (b.rank == null) {
        return -1;
      }
      return a.rank - b.rank;
    });
  }, [tableRows, query, publicOnly]);

  return (
    <Box
      sx={{
        display: "flex",
        height: "100%",
        minHeight: 0,
        gap: 1.25,
        p: 1.25,
        position: "relative",
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
          gap: 1,
          p: 1.25,
          overflowX: "hidden",
          overflowY: "auto",
          border: "1px solid #2a3038",
          borderRadius: "8px",
          backgroundColor: "#0b0e12",
          ...scrollSx,
        }}
      >
        {listLoading ? (
          <Box
            sx={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 1.25,
              flex: 1,
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
      <Box
        sx={{
          flex: 1,
          minWidth: 0,
          height: "100%",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <RaceMeta
          race={races.find((row) => row.race_id === selectedId) ?? null}
          query={query}
          onQuery={setQuery}
          publicOnly={publicOnly}
          onPublicOnly={() => setPublicOnly((on) => !on)}
        />
        <Box
          sx={{
            flex: 1,
            minHeight: 0,
            overflow: "hidden",
            border: "1px solid #2a3038",
            borderRadius: "8px",
            backgroundColor: "#12171d",
            ...scrollSx,
          }}
        >
          <SelectedRaceTable
            rows={visibleRows}
            loading={tableLoading}
            activeVersionId={codeRow?.agent_version_id}
            onPublicClick={(row) =>
              setCodeRow((current) =>
                current?.agent_version_id === row.agent_version_id ? null : row
              )
            }
          />
        </Box>
      </Box>
      {codeRow ? (
        <Box
          sx={{
            position: "absolute",
            top: 10,
            right: 10,
            bottom: 10,
            width: 420,
            zIndex: 20,
            display: "flex",
            flexDirection: "column",
            border: "1px solid #2a3038",
            borderRadius: "8px",
            backgroundColor: "#0b0e12",
            boxShadow: "0 12px 40px rgba(0,0,0,0.55)",
            overflow: "hidden",
          }}
        >
          <Box
            sx={{
              display: "flex",
              alignItems: "center",
              gap: 1,
              px: 1.25,
              py: 0.85,
              borderBottom: "1px solid #2a3038",
              flexShrink: 0,
            }}
          >
            <Typography
              sx={{
                color: "#c5c9d0",
                fontSize: "0.82rem",
                fontWeight: 700,
                minWidth: 0,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                flex: 1,
              }}
            >
              {codeRow.agent_name}
              {codeRow.version_number != null ? ` v${codeRow.version_number}` : ""}
            </Typography>
            <IconButton
              size="small"
              onClick={() => setCodeRow(null)}
              sx={{ color: "#8a8f98", p: 0.25, "&:hover": { color: "#c5c9d0" } }}
            >
              <Close sx={{ fontSize: 16 }} />
            </IconButton>
          </Box>
          {codeFiles.length > 1 ? (
            <Box
              sx={{
                display: "flex",
                gap: 0.5,
                px: 1.25,
                py: 0.6,
                borderBottom: "1px solid #2a3038",
                overflow: "auto",
                flexShrink: 0,
              }}
            >
              {codeFiles.map((file, index) => (
                <Box
                  key={`${file.name}-${index}`}
                  component="button"
                  type="button"
                  onClick={() => setCodeFile(index)}
                  sx={{
                    border: 0,
                    borderRadius: "4px",
                    px: 0.8,
                    py: 0.25,
                    cursor: "pointer",
                    fontFamily: "inherit",
                    fontSize: "0.68rem",
                    color: index === codeFile ? "#3ecf8e" : "#8a8f98",
                    backgroundColor: index === codeFile ? "#163028" : "transparent",
                  }}
                >
                  {file.name}
                </Box>
              ))}
            </Box>
          ) : null}
          <Box sx={{ flex: 1, minHeight: 0, ...scrollSx, p: 1.25 }}>
            {codeLoading ? (
              <Box
                sx={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 1.25,
                  height: "100%",
                  color: "#8a8f98",
                  fontSize: "0.78rem",
                }}
              >
                <CircularProgress size={16} sx={{ color: "#8a8f98" }} />
                Loading
              </Box>
            ) : (
              <Box
                component="pre"
                sx={{
                  m: 0,
                  color: "#c5c9d0",
                  fontFamily: mono,
                  fontSize: "0.72rem",
                  lineHeight: 1.45,
                  whiteSpace: "pre",
                }}
              >
                {codeFiles[codeFile]?.text || "-"}
              </Box>
            )}
          </Box>
        </Box>
      ) : null}
    </Box>
  );
}
