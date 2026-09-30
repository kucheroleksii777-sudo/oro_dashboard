import { useEffect, useState } from "react";
import Refresh from "@mui/icons-material/Refresh";
import Box from "@mui/material/Box";

const mono =
  'ui-monospace, "SFMono-Regular", "Cascadia Mono", "Roboto Mono", Menlo, Consolas, monospace';

const badgeSx = {
  display: "flex",
  alignItems: "center",
  gap: 0.75,
  px: 1,
  py: "5px",
  borderRadius: "5px",
  backgroundColor: "#1c1f26",
  border: "1px solid #2e343c",
  fontFamily: mono,
  fontSize: "0.78rem",
  lineHeight: 1.2,
  whiteSpace: "nowrap",
} as const;

function formatTao(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return "—";
  }
  return `τ${value.toFixed(4)}`;
}

function formatAlpha(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return "—";
  }
  return `τ${value.toFixed(8)}`;
}

function formatJst(now: Date): string {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Tokyo",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).formatToParts(now);
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  return `JST ${get("month")}-${get("day")} ${get("hour")}:${get("minute")}:${get("second")}`;
}

function formatUsd(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return "—";
  }
  return `$${value.toFixed(2)}`;
}

export function RegistrationBadge({
  regTao,
}: {
  regTao: number | null;
}) {
  return (
    <Box sx={badgeSx} title="SN15 miner registration (recycle) fee">
      <Box component="span" sx={{ color: "#8a8f98" }}>
        SN15 reg
      </Box>
      <Box component="span" sx={{ color: "#3ecf8e", fontWeight: 600 }}>
        {formatTao(regTao)}
      </Box>
    </Box>
  );
}

export default function HeaderStats({
  regTao,
  alphaTao,
  taoUsd,
  refreshing,
  onRefresh,
}: {
  regTao: number | null;
  alphaTao: number | null;
  taoUsd: number | null;
  refreshing?: boolean;
  onRefresh?: () => void;
}) {
  const [clock, setClock] = useState(() => formatJst(new Date()));

  useEffect(() => {
    const tick = window.setInterval(() => {
      setClock(formatJst(new Date()));
    }, 1000);
    return () => window.clearInterval(tick);
  }, []);

  return (
    <Box
      sx={{
        ml: "auto",
        display: "flex",
        alignItems: "center",
        gap: 0.75,
        flexShrink: 0,
      }}
    >
      <Box
        component="button"
        type="button"
        title="Refresh TAO, reg, and alpha prices"
        onClick={() => onRefresh?.()}
        disabled={refreshing}
        sx={{
          ...badgeSx,
          cursor: refreshing ? "wait" : "pointer",
          color: "#8a8f98",
          "&:hover": { color: "#c5c9d0", borderColor: "#e89b25" },
        }}
      >
        <Refresh
          sx={{
            fontSize: 16,
            animation: refreshing ? "oroSpin 0.8s linear infinite" : "none",
            "@keyframes oroSpin": {
              to: { transform: "rotate(360deg)" },
            },
          }}
        />
      </Box>
      <Box sx={badgeSx} title="TAO price in USD">
        <Box component="span" sx={{ color: "#8a8f98" }}>
          TAO
        </Box>
        <Box component="span" sx={{ color: "#f5d76e", fontWeight: 600 }}>
          {formatUsd(taoUsd)}
        </Box>
      </Box>
      <RegistrationBadge regTao={regTao} />
      <Box sx={badgeSx} title="SN15 alpha price in TAO">
        <Box component="span" sx={{ color: "#8a8f98" }}>
          alpha
        </Box>
        <Box component="span" sx={{ color: "#e89b25", fontWeight: 600 }}>
          {formatAlpha(alphaTao)}
        </Box>
      </Box>
      <Box sx={{ ...badgeSx, color: "#f3f4f6" }} title="Japan Standard Time">
        {clock}
      </Box>
    </Box>
  );
}
