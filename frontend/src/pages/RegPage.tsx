import { useEffect, useMemo, useState } from "react";
import Box from "@mui/material/Box";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Typography from "@mui/material/Typography";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  fetchRegisteredUids,
  fetchRegistrationHistory,
  type RegisteredUid,
  type RegistrationHistory,
  type RegistrationSpan,
} from "../api";
import UidTable from "./RegisteredUidsTable";

const SPANS: RegistrationSpan[] = ["1D", "1W", "1M", "1Y", "ALL"];

const mono =
  'ui-monospace, "SFMono-Regular", "Cascadia Mono", "Roboto Mono", Menlo, Consolas, monospace';

function formatTao(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return "—";
  }
  return `τ${value.toFixed(4)}`;
}

const HOUR_MS = 60 * 60 * 1000;
const DAY_MS = 24 * HOUR_MS;

function axisTicks(points: Array<{ t: number }>, span: RegistrationSpan): number[] {
  if (!points.length) {
    return [];
  }
  const min = points[0].t;
  const max = points[points.length - 1].t;
  const step = span === "1D" ? HOUR_MS : span === "1W" || span === "1M" ? DAY_MS : 30 * DAY_MS;
  const start = Math.ceil(min / step) * step;
  const ticks: number[] = [];
  for (let time = start; time <= max; time += step) {
    ticks.push(time);
  }
  return ticks.length ? ticks : [min, max];
}

function formatAxisTime(timestamp: number, span: RegistrationSpan): string {
  const options: Intl.DateTimeFormatOptions =
    span === "1D"
      ? { timeZone: "Asia/Tokyo", hour: "2-digit", minute: "2-digit", hour12: false }
      : span === "1Y" || span === "ALL"
        ? { timeZone: "Asia/Tokyo", year: "2-digit", month: "2-digit" }
        : { timeZone: "Asia/Tokyo", month: "2-digit", day: "2-digit" };
  return new Intl.DateTimeFormat("en-GB", options).format(new Date(timestamp));
}

function formatTooltipTime(timestamp: number): string {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(new Date(timestamp));
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")} ${get("hour")}:${get("minute")}`;
}

function SpecialDot({
  cx,
  cy,
  index,
  lastIndex,
}: {
  cx?: number;
  cy?: number;
  index?: number;
  lastIndex: number;
}) {
  if (cx == null || cy == null || index !== lastIndex) {
    return null;
  }
  return (
    <g>
      <circle cx={cx} cy={cy} r={9} fill="#4ea1ff" fillOpacity={0.22} />
      <circle cx={cx} cy={cy} r={4.5} fill="#0b0e12" stroke="#4ea1ff" strokeWidth={2} />
      <circle cx={cx} cy={cy} r={2.2} fill="#4ea1ff" />
    </g>
  );
}

function ChartTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: { t: number; tao: number } }>;
}) {
  if (!active || !payload?.length) {
    return null;
  }
  const point = payload[0].payload;
  return (
    <Box
      sx={{
        px: 1.25,
        py: 0.75,
        backgroundColor: "#1c1f26",
        border: "1px solid #2e343c",
        borderRadius: "6px",
      }}
    >
      <Typography sx={{ color: "#8a8f98", fontSize: "0.75rem", fontFamily: mono }}>
        JST {formatTooltipTime(point.t)}
      </Typography>
      <Typography
        sx={{ color: "#4ea1ff", fontSize: "0.9rem", fontWeight: 600, fontFamily: mono }}
      >
        {formatTao(point.tao)}
      </Typography>
    </Box>
  );
}

export default function RegPage({
  regTao,
  keysLabel,
}: {
  regTao: number | null;
  keysLabel: string;
}) {
  const [span, setSpan] = useState<RegistrationSpan>("1D");
  const [histories, setHistories] = useState<
    Partial<Record<RegistrationSpan, RegistrationHistory>>
  >({});
  const [loadingSpan, setLoadingSpan] = useState<RegistrationSpan | null>("1D");
  const [registeredRows, setRegisteredRows] = useState<RegisteredUid[]>([]);
  const [removedRows, setRemovedRows] = useState<RegisteredUid[]>([]);
  const [uidsLoading, setUidsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    const load = async (showLoading: boolean) => {
      if (showLoading) {
        setLoadingSpan(span);
      }
      const data = await fetchRegistrationHistory(span);
      if (cancelled) {
        return;
      }
      if (data) {
        setHistories((current) => ({ ...current, [span]: data }));
      }
      setLoadingSpan((current) => (current === span ? null : current));
    };

    void load(true);
    return () => {
      cancelled = true;
    };
  }, [span]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      const data = await fetchRegisteredUids();
      if (cancelled) {
        return;
      }
      setRegisteredRows(data?.rows ?? []);
      setRemovedRows(data?.to_be_removed ?? []);
      setUidsLoading(false);
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const history = histories[span] ?? null;
  const points = useMemo(() => {
    const series = history?.points ?? [];
    if (!series.length || regTao == null) {
      return series;
    }
    const next = series.slice();
    next[next.length - 1] = { t: Date.now(), tao: regTao };
    return next;
  }, [history, regTao]);
  const currentTao = regTao ?? history?.current_tao ?? null;
  const loading = loadingSpan === span && !history;
  const yDomain = useMemo(() => {
    if (!points.length) {
      return [0, 1] as [number, number];
    }
    const values = points.map((point) => point.tao);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const pad = Math.max((max - min) * 0.2, 0.002);
    return [Math.max(0, min - pad), max + pad] as [number, number];
  }, [points]);
  const xTicks = useMemo(() => axisTicks(points, span), [points, span]);

  return (
    <Box sx={{ height: "100%", overflow: "auto", p: { xs: 1.5, md: 2 } }}>
      <Box
        sx={{
          backgroundColor: "#12171d",
          border: "1px solid #2a3038",
          borderRadius: "10px",
          p: { xs: 1.5, md: 2 },
        }}
      >
        <Box
          sx={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 1.5,
            flexWrap: "wrap",
            mb: 1.5,
          }}
        >
          <Box sx={{ display: "flex", alignItems: "baseline", gap: 1.25 }}>
            <Typography sx={{ color: "#f3f4f6", fontSize: "1.05rem", fontWeight: 600 }}>
              Registration cost
            </Typography>
            <Typography
              sx={{
                color: "#4ea1ff",
                fontFamily: mono,
                fontSize: "1.15rem",
                fontWeight: 700,
              }}
            >
              {loading && !points.length ? "…" : formatTao(currentTao)}
            </Typography>
          </Box>
          <ToggleButtonGroup
            exclusive
            size="small"
            value={span}
            onChange={(_event, next: RegistrationSpan | null) => {
              if (next) {
                setSpan(next);
              }
            }}
            sx={{
              backgroundColor: "#1c1f26",
              "& .MuiToggleButton-root": {
                color: "#8a8f98",
                borderColor: "#2e343c",
                px: 1.25,
                py: 0.25,
                fontSize: "0.75rem",
                fontWeight: 600,
                "&.Mui-selected": {
                  color: "#4ea1ff",
                  backgroundColor: "#15202c",
                  borderColor: "#4ea1ff",
                },
                "&.Mui-selected:hover": {
                  color: "#4ea1ff",
                  backgroundColor: "#1a2836",
                  borderColor: "#4ea1ff",
                },
              },
            }}
          >
            {SPANS.map((value) => (
              <ToggleButton key={value} value={value}>
                {value === "ALL" ? "All" : value}
              </ToggleButton>
            ))}
          </ToggleButtonGroup>
        </Box>
        <Box sx={{ height: { xs: 280, md: 380 }, position: "relative" }}>
          {loading && !points.length ? (
            <Box
              sx={{
                height: "100%",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "#8a8f98",
              }}
            >
              Loading chart…
            </Box>
          ) : !points.length ? (
            <Box
              sx={{
                height: "100%",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "#8a8f98",
              }}
            >
              No registration history
            </Box>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={points} margin={{ top: 8, right: 4, left: 8, bottom: 4 }}>
                <defs>
                  <linearGradient id="regCostFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#4ea1ff" stopOpacity={0.28} />
                    <stop offset="100%" stopColor="#4ea1ff" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="#222830" strokeDasharray="4 0" vertical={false} />
                <XAxis
                  xAxisId="bottom"
                  dataKey="t"
                  type="number"
                  domain={["dataMin", "dataMax"]}
                  ticks={xTicks}
                  interval={0}
                  tickFormatter={(value: number) => formatAxisTime(value, span)}
                  tick={{ fill: "#8a8f98", fontSize: 11, dy: 12 }}
                  axisLine={{ stroke: "#2e343c" }}
                  tickLine={false}
                  height={32}
                  padding={{ right: 78 }}
                />
                <YAxis
                  yAxisId="right"
                  orientation="right"
                  mirror
                  domain={yDomain}
                  tickCount={10}
                  tickFormatter={(value: number) => `τ${Number(value).toFixed(4)}`}
                  tick={{
                    fill: "#8a8f98",
                    fontSize: 11,
                    fontFamily: mono,
                    textAnchor: "end",
                  }}
                  axisLine={false}
                  tickLine={false}
                  width={76}
                  allowDecimals
                  allowDataOverflow
                />
                <Tooltip content={<ChartTooltip />} />
                <Area
                  xAxisId="bottom"
                  yAxisId="right"
                  type="monotone"
                  dataKey="tao"
                  stroke="#4ea1ff"
                  strokeWidth={2}
                  fill="url(#regCostFill)"
                  isAnimationActive={false}
                  dot={(props) => (
                    <SpecialDot
                      cx={props.cx}
                      cy={props.cy}
                      index={props.index}
                      lastIndex={points.length - 1}
                    />
                  )}
                  activeDot={{
                    r: 5,
                    fill: "#4ea1ff",
                    stroke: "#0b0e12",
                    strokeWidth: 2,
                  }}
                />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </Box>
        <Typography sx={{ mt: 1, color: "#6b717a", fontSize: "0.72rem" }}>
          SN15 miner registration (recycle) fee, same series as{" "}
          <Box
            component="a"
            href="https://taomarketcap.com/subnets/15/registration"
            target="_blank"
            rel="noreferrer"
            sx={{ color: "#8a8f98", textDecoration: "underline" }}
          >
            TaoMarketCap
          </Box>
          . Times in JST.
        </Typography>
      </Box>
      <Box
        sx={{
          mt: 2,
          display: "flex",
          alignItems: "flex-start",
          gap: 2,
          flexWrap: { xs: "wrap", md: "nowrap" },
        }}
      >
        <Box sx={{ width: { xs: "100%", md: "50%" }, minWidth: 0 }}>
          <UidTable
            title="Registered UIDs"
            rows={registeredRows}
            loading={uidsLoading}
            keysLabel={keysLabel}
          />
        </Box>
        <Box sx={{ width: { xs: "100%", md: "50%" }, minWidth: 0 }}>
          <UidTable
            title="To be Removed"
            rows={removedRows}
            loading={uidsLoading}
            keysLabel={keysLabel}
          />
        </Box>
      </Box>
    </Box>
  );
}
