import { useEffect, useMemo, useRef, useState } from "react";
import Box from "@mui/material/Box";
import IconButton from "@mui/material/IconButton";
import Modal from "@mui/material/Modal";
import Close from "@mui/icons-material/Close";

import type { ScoreMode, TrendPoint } from "../api";

type TabId = "o" | "r" | "p" | "s" | "v" | "tf1" | "tf2" | "tf3" | "tf4" | "tf5" | "tf6" | "tf7";

const BASE_TABS: Array<{ id: TabId; label: string; color: string }> = [
  { id: "o", label: "Overall", color: "#4ea1ff" },
  { id: "r", label: "Race", color: "#3ecf8e" },
];

const PSV_TABS: Array<{ id: TabId; label: string; color: string }> = [
  { id: "p", label: "Product", color: "#b57bff" },
  { id: "s", label: "Shop", color: "#f5d76e" },
  { id: "v", label: "Voucher", color: "#ff7eb6" },
];

const TF_TABS: Array<{ id: TabId; label: string; color: string }> = [
  { id: "tf1", label: "TF1", color: "#a3e635" },
  { id: "tf2", label: "TF2", color: "#818cf8" },
  { id: "tf3", label: "TF3", color: "#ff7eb6" },
  { id: "tf4", label: "TF4", color: "#ffb020" },
  { id: "tf5", label: "TF5", color: "#c084fc" },
  { id: "tf6", label: "TF6", color: "#22d3ee" },
  { id: "tf7", label: "TF7", color: "#fb923c" },
];

function tabsFor(mode: ScoreMode): Array<{ id: TabId; label: string; color: string }> {
  return [...BASE_TABS, ...(mode === "tf" ? TF_TABS : PSV_TABS)];
}

function isCountTab(tab: TabId): boolean {
  return tab === "p" || tab === "s" || tab === "v" || tab.startsWith("tf");
}

const MUTED = "#8b949e";
const ORANGE = "#e89b25";

function darken(hex: string, amount = 0.32): string {
  const raw = hex.replace("#", "");
  const r = parseInt(raw.slice(0, 2), 16);
  const g = parseInt(raw.slice(2, 4), 16);
  const b = parseInt(raw.slice(4, 6), 16);
  const f = 1 - amount;
  return `rgb(${Math.round(r * f)},${Math.round(g * f)},${Math.round(b * f)})`;
}

type Slot = {
  race_number: number;
  score: number | null;
  mid: number | null;
  margin: number | null;
  rank: number | null;
};

function pointScore(point: TrendPoint, tab: TabId): number | null {
  const value =
    tab === "o"
      ? (point.o_score ?? point.score)
      : tab === "r"
        ? (point.r_score ?? point.score)
        : tab === "p"
          ? point.p_score
          : tab === "s"
            ? point.s_score
            : tab === "v"
              ? point.v_score
              : point[`${tab}_score`];
  return value == null || !Number.isFinite(value) ? null : value;
}

function pointMid(point: TrendPoint, tab: TabId): number | null {
  const value =
    tab === "o"
      ? point.o_mid
      : tab === "r"
        ? (point.anchor ?? point.r_mid)
        : tab === "p"
          ? point.p_mid
          : tab === "s"
            ? point.s_mid
            : tab === "v"
              ? point.v_mid
              : point[`${tab}_mid`];
  return value == null || !Number.isFinite(value) ? null : value;
}

function pointRank(point: TrendPoint, tab: TabId): number | null {
  const value =
    tab === "o"
      ? point.o_rank
      : tab === "r"
        ? point.r_rank
        : tab === "p"
          ? point.p_rank
          : tab === "s"
            ? point.s_rank
            : tab === "v"
              ? point.v_rank
              : point[`${tab}_rank`];
  return value != null && Number.isFinite(value) ? value : null;
}

function formatMargin(value: number | null): string {
  if (value == null) {
    return "—";
  }
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}`;
}

function buildSlots(points: TrendPoint[], tab: TabId): Slot[] {
  const byRace = new Map<number, TrendPoint>();
  for (const point of points) {
    if (point.race_number != null) {
      byRace.set(point.race_number, point);
    }
  }
  const numbers = [...byRace.keys()]
    .filter((number) => {
      const point = byRace.get(number);
      return point != null && pointScore(point, tab) != null && pointMid(point, tab) != null;
    })
    .sort((a, b) => a - b);
  if (!numbers.length) {
    return [];
  }
  const scale = isCountTab(tab) ? 1 : 100;
  const slots: Slot[] = [];
  for (let number = numbers[0]; number <= numbers[numbers.length - 1]; number += 1) {
    const point = byRace.get(number);
    const score = point ? pointScore(point, tab) : null;
    const mid = point ? pointMid(point, tab) : null;
    slots.push({
      race_number: number,
      score,
      mid,
      margin: score != null && mid != null ? (score - mid) * scale : null,
      rank: point ? pointRank(point, tab) : null,
    });
  }
  return slots;
}

export default function TrendDialog({
  name,
  version,
  tab,
  first,
  last,
  points,
  scoreMode = "psv",
  onClose,
}: {
  name: string;
  version: number | null;
  tab: "o" | "r";
  first: number | null;
  last: number | null;
  points: TrendPoint[];
  scoreMode?: ScoreMode;
  onClose: () => void;
}) {
  const tabs = useMemo(() => tabsFor(scoreMode), [scoreMode]);
  const armed = useRef(false);
  const [selected, setSelected] = useState<TabId[]>([tab]);
  useEffect(() => {
    setSelected([tab]);
  }, [tab, scoreMode]);
  const series = useMemo(
    () =>
      tabs.filter((item) => selected.includes(item.id)).map((item) => ({
        ...item,
        slots: buildSlots(points ?? [], item.id),
      })),
    [points, selected, tabs],
  );
  const selectedLabels = series.map((item) => item.label).join(" · ") || "—";

  const toggleTab = (id: TabId) => {
    setSelected((current) => {
      if (current.includes(id)) {
        return current.length === 1 ? current : current.filter((item) => item !== id);
      }
      return [...current, id];
    });
  };

  useEffect(() => {
    armed.current = false;
    const arm = () => {
      armed.current = true;
    };
    window.addEventListener("pointerup", arm, { once: true });
    const timer = window.setTimeout(arm, 250);
    return () => {
      window.removeEventListener("pointerup", arm);
      window.clearTimeout(timer);
    };
  }, []);

  return (
    <Modal
      open
      onClose={(_event, reason) => {
        if (reason === "backdropClick" && !armed.current) {
          return;
        }
        onClose();
      }}
      disableAutoFocus
      disableEnforceFocus
      disableRestoreFocus
      slotProps={{
        backdrop: {
          sx: { backgroundColor: "rgba(0, 0, 0, 0.55)" },
        },
      }}
    >
      <Box
        tabIndex={-1}
        sx={{
          position: "absolute",
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          width: scoreMode === "tf" ? 880 : 780,
          height: 610,
          display: "flex",
          flexDirection: "column",
          overflow: "visible",
          outline: "none",
          backgroundColor: "#0f1729",
          border: "1px solid #1c2940",
          borderRadius: "14px",
          color: "#c5c9d0",
          boxShadow: "0 16px 48px rgba(0,0,0,0.55)",
        }}
      >
        <Box sx={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", px: 2.25, pt: 3, pb: 2.5 }}>
          <Box sx={{ minWidth: 0, pr: 1.5 }}>
            <Box
              sx={{
                color: "#ffffff",
                fontWeight: 800,
                fontSize: "1.15rem",
                lineHeight: 1.2,
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              {`${name}${version != null ? ` v${version}` : ""} — ${tab === "o" ? "O Trend" : "R Trend"}`}
            </Box>
            <Box
              sx={{
                color: MUTED,
                fontSize: "0.78rem",
                mt: 0.9,
                lineHeight: 1.4,
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              {`${selectedLabels} · ${
                first != null && last != null ? `R${first}–R${last}` : "—"
              } · Y-axis = margin (higher = better) · hover a line to focus · click tabs to toggle`}
            </Box>
          </Box>
          <IconButton onClick={onClose} sx={{ color: MUTED, "&:hover": { color: "#ffffff" } }}>
            <Close />
          </IconButton>
        </Box>
        <Box sx={{ display: "flex", gap: 0.7, px: 2.25, pt: 0.5, pb: 2.25 }}>
          {tabs.map((item) => {
            const on = selected.includes(item.id);
            return (
              <Box
                key={item.id}
                component="button"
                type="button"
                onClick={() => toggleTab(item.id)}
                sx={{
                  px: 1.25,
                  py: 0.55,
                  borderRadius: "7px",
                  border: `1px solid ${on ? item.color : "#2a3344"}`,
                  backgroundColor: on ? `${item.color}22` : "#121a2e",
                  color: on ? item.color : MUTED,
                  fontWeight: 700,
                  fontSize: "0.78rem",
                  cursor: "pointer",
                  fontFamily: "inherit",
                  transition: "transform 0.16s ease, color 0.16s ease",
                  "&:hover": {
                    transform: "translateY(-3px)",
                    color: "#ffffff",
                  },
                }}
              >
                {item.label}
              </Box>
            );
          })}
        </Box>
        <Box
          sx={{
            width: scoreMode === "tf" ? 844 : 744,
            height: 446,
            flex: "0 0 446px",
            mx: "auto",
            mb: 2.25,
            border: "1px solid #2a3a58",
            borderRadius: "12px",
            overflow: "hidden",
            backgroundColor: "#0f1629",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            boxSizing: "border-box",
          }}
        >
          <TrendChart series={series} />
        </Box>
      </Box>
    </Modal>
  );
}

function TrendChart({
  series,
}: {
  series: Array<{ id: TabId; label: string; color: string; slots: Slot[] }>;
}) {
  const [hover, setHover] = useState<{ race: number; tab: TabId } | null>(null);
  const width = 720;
  const height = 420;
  const left = 48;
  const right = 16;
  const top = 36;
  const bottom = 24;
  const plotW = width - left - right;
  const plotH = height - top - bottom;
  const axis = series.find((item) => item.slots.length)?.slots ?? [];
  const plotted = series.flatMap((item) => item.slots.filter((slot) => slot.margin != null));
  if (!axis.length || !plotted.length) {
    return (
      <Box sx={{ height: "100%", display: "grid", placeItems: "center", color: MUTED }}>
        No trend data
      </Box>
    );
  }
  const values = plotted.map((slot) => slot.margin as number);
  const yMin = Math.min(0, ...values);
  const yMax = Math.max(0, ...values);
  const pad = Math.max(2, (yMax - yMin) * 0.12);
  const y0 = yMin - pad;
  const y1 = yMax + pad;
  const span = y1 - y0 || 1;
  const xAt = (index: number) =>
    axis.length === 1 ? (left + width - right) / 2 : left + (index / (axis.length - 1)) * (width - left - right);
  const yAt = (value: number) => top + (1 - (value - y0) / span) * (height - top - bottom);
  const ticks = [y1, 0, y0].filter((value, index, all) => all.indexOf(value) === index);
  const lines = series.map((item) => ({
    ...item,
    points: item.slots
      .map((slot, index) => (slot.margin == null ? null : `${xAt(index)},${yAt(slot.margin)}`))
      .filter((value): value is string => value != null),
  }));
  const hoverColor = series.find((item) => item.id === hover?.tab)?.color ?? series[0]?.color ?? "#4ea1ff";

  const marks = (() => {
    const labelW = 76;
    const labelH = 16;
    const gap = 34;
    const space = 6;
    const minX = left + 2;
    const maxX = left + plotW - labelW - 2;
    const minY = top + 2;
    const maxY = top + plotH - labelH - 2;
    const hits = (
      a: { boxX: number; boxY: number; labelW: number; labelH: number },
      b: { boxX: number; boxY: number; labelW: number; labelH: number },
    ) =>
      a.boxX < b.boxX + b.labelW + space &&
      a.boxX + a.labelW + space > b.boxX &&
      a.boxY < b.boxY + b.labelH + space &&
      a.boxY + a.labelH + space > b.boxY;
    const items = series
      .flatMap((item) =>
        item.slots.map((slot, index) => {
          if (slot.margin == null) {
            return null;
          }
          const x = xAt(index);
          const y = yAt(slot.margin);
          let boxX = x - labelW / 2;
          let boxY = index % 2 === 0 ? y - gap - labelH : y + gap;
          if (boxY < minY) {
            boxY = y + gap;
          }
          if (boxY > maxY) {
            boxY = y - gap - labelH;
          }
          return {
            slot,
            tab: item.id,
            tabLabel: item.label,
            color: item.color,
            x,
            y,
            boxX: Math.min(Math.max(boxX, minX), maxX),
            boxY: Math.min(Math.max(boxY, minY), maxY),
            labelW,
            labelH,
          };
        }),
      )
      .filter((item): item is NonNullable<typeof item> => item != null)
      .sort((a, b) => a.x - b.x || a.tab.localeCompare(b.tab));
    for (let i = 0; i < items.length; i += 1) {
      const cur = items[i];
      for (let step = 0; step < 48; step += 1) {
        const hit = items.slice(0, i).find((other) => hits(cur, other));
        if (!hit) {
          break;
        }
        const goDown = cur.boxY + cur.labelH / 2 >= hit.boxY + hit.labelH / 2;
        cur.boxY = goDown ? hit.boxY + hit.labelH + space : hit.boxY - cur.labelH - space;
        if (cur.boxY < minY) {
          cur.boxY = hit.boxY + hit.labelH + space;
        }
        if (cur.boxY > maxY) {
          cur.boxY = hit.boxY - cur.labelH - space;
        }
        cur.boxY = Math.min(Math.max(cur.boxY, minY), maxY);
        if (hits(cur, hit)) {
          cur.boxX = cur.x >= hit.x ? hit.boxX + hit.labelW + space : hit.boxX - cur.labelW - space;
          cur.boxX = Math.min(Math.max(cur.boxX, minX), maxX);
        }
      }
    }
    return items;
  })();

  return (
    <Box sx={{ width, height, flex: "none" }}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width={width}
        height={height}
        onMouseLeave={() => setHover(null)}
      >
        <text x={8} y={18} fill={MUTED} fontSize="11" fontWeight="700">
          MARGIN
        </text>
        <rect
          x={left}
          y={top}
          width={width - left - right}
          height={height - top - bottom}
          fill="none"
          stroke="#2a3a58"
        />
        {ticks.map((tick) => (
          <g key={tick}>
            <line
              x1={left}
              x2={width - right}
              y1={yAt(tick)}
              y2={yAt(tick)}
              stroke={tick === 0 ? "#2a3348" : "#243044"}
              strokeWidth={tick === 0 ? 1.4 : 1}
              strokeDasharray={tick === 0 ? undefined : "2 6"}
            />
            <text x={left - 8} y={yAt(tick) + 3} textAnchor="end" fill={MUTED} fontSize="10">
              {tick > 0 ? `+${tick.toFixed(0)}` : tick.toFixed(0)}
            </text>
          </g>
        ))}
        <defs>
          <filter id="trend-line-shadow" x="-70%" y="-70%" width="240%" height="240%">
            <feGaussianBlur in="SourceAlpha" stdDeviation="2.2" result="b1" />
            <feGaussianBlur in="SourceAlpha" stdDeviation="5" result="b2" />
            <feGaussianBlur in="SourceAlpha" stdDeviation="9.5" result="b3" />
            <feFlood floodColor={hoverColor} floodOpacity="0.62" result="c1" />
            <feFlood floodColor={hoverColor} floodOpacity="0.34" result="c2" />
            <feFlood floodColor="#000000" floodOpacity="0.4" result="c3" />
            <feComposite in="c1" in2="b1" operator="in" result="s1" />
            <feComposite in="c2" in2="b2" operator="in" result="s2" />
            <feComposite in="c3" in2="b3" operator="in" result="s3" />
            <feMerge>
              <feMergeNode in="s3" />
              <feMergeNode in="s2" />
              <feMergeNode in="s1" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <filter id="trend-dot-glow" x="-80%" y="-80%" width="260%" height="260%">
            <feGaussianBlur stdDeviation="4.5" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
            </feMerge>
          </filter>
        </defs>
        {[...lines]
          .sort((a, b) => (a.id === hover?.tab ? 1 : b.id === hover?.tab ? -1 : 0))
          .map((item) =>
            item.points.length > 1 ? (
              <polyline
                key={item.id}
                fill="none"
                stroke={item.color}
                strokeWidth="2.8"
                points={item.points.join(" ")}
                filter={hover?.tab === item.id ? "url(#trend-line-shadow)" : undefined}
              />
            ) : null,
          )}
        {axis.map((slot, index) => {
          const hasValue = series.some((item) => item.slots[index]?.margin != null);
          if (!hasValue) {
            return null;
          }
          return (
            <text key={`x-${slot.race_number}`} x={xAt(index)} y={height - 4} textAnchor="middle" fill={MUTED} fontSize="12" fontWeight="600">
              {`R${slot.race_number}`}
            </text>
          );
        })}
        {[...marks]
          .sort((a, b) =>
            a.slot.race_number === hover?.race && a.tab === hover?.tab
              ? 1
              : b.slot.race_number === hover?.race && b.tab === hover?.tab
                ? -1
                : 0,
          )
          .map((mark) => {
          const { slot, x, y, boxX, boxY, labelW, labelH, color, tab, tabLabel } = mark;
          const isTop = slot.rank === 1;
          const cx = boxX + labelW / 2;
          const cy = boxY + labelH / 2;
          const dx = x - cx;
          const dy = y - cy;
          const attach =
            Math.abs(dx / (labelW / 2)) > Math.abs(dy / (labelH / 2))
              ? { ax: dx > 0 ? boxX + labelW : boxX, ay: cy }
              : { ax: cx, ay: dy > 0 ? boxY + labelH : boxY };
          const vx = attach.ax - x;
          const vy = attach.ay - y;
          const len = Math.hypot(vx, vy) || 1;
          const on = hover?.race === slot.race_number && hover.tab === tab;
          const startX = x + (vx / len) * (on ? 11 : 5);
          const startY = y + (vy / len) * (on ? 11 : 5);
          const border = darken(color, 0.48);
          return (
            <g key={`${tab}-${slot.race_number}`}>
              <line
                x1={startX}
                y1={startY}
                x2={attach.ax}
                y2={attach.ay}
                stroke="#2a3344"
                strokeWidth="0.9"
              />
              <rect
                x={boxX}
                y={boxY}
                width={labelW}
                height={labelH}
                rx={8}
                fill="#0f1729"
                stroke={border}
                strokeWidth="0.9"
              />
              <text x={cx} y={boxY + 11.5} textAnchor="middle" fontSize="9" fontWeight="700">
                <tspan fill={color}>{formatMargin(slot.margin)}</tspan>
                {slot.rank != null ? (
                  <tspan fill={isTop ? ORANGE : color}>{`(#${slot.rank})`}</tspan>
                ) : null}
              </text>
              {on ? (
                <>
                  <circle
                    cx={x}
                    cy={y}
                    r={16}
                    fill={color}
                    opacity="0.22"
                    filter="url(#trend-dot-glow)"
                  />
                  <circle cx={x} cy={y} r={11} fill="none" stroke={color} strokeWidth="1.4" />
                  <circle cx={x} cy={y} r={6.5} fill={color} />
                </>
              ) : (
                <circle cx={x} cy={y} r={4} fill={color} stroke={color} strokeWidth="1.2" />
              )}
              <circle
                cx={x}
                cy={y}
                r={12}
                fill="transparent"
                style={{ cursor: "pointer" }}
                onMouseEnter={() => setHover({ race: slot.race_number, tab })}
                onMouseLeave={() => setHover(null)}
              />
              {on ? (
                <HoverTip
                  x={x}
                  y={y}
                  slot={slot}
                  tab={tab}
                  tabLabel={tabLabel}
                  left={left}
                  top={top}
                  plotW={plotW}
                  plotH={plotH}
                />
              ) : null}
            </g>
          );
        })}
      </svg>
    </Box>
  );
}

function HoverTip({
  x,
  y,
  slot,
  tab,
  tabLabel,
  left,
  top,
  plotW,
  plotH,
}: {
  x: number;
  y: number;
  slot: Slot;
  tab: TabId;
  tabLabel: string;
  left: number;
  top: number;
  plotW: number;
  plotH: number;
}) {
  const tipW = 138;
  const tipH = 64;
  let tipX = x + 18;
  let tipY = y + 20;
  if (tipX + tipW > left + plotW - 4) {
    tipX = x - tipW - 14;
  }
  if (tipY + tipH > top + plotH - 4) {
    tipY = y - tipH - 16;
  }
  tipX = Math.min(Math.max(tipX, left + 4), left + plotW - tipW - 4);
  tipY = Math.min(Math.max(tipY, top + 4), top + plotH - tipH - 4);
  const value = `${formatMargin(slot.margin)}${slot.rank != null ? `(#${slot.rank})` : ""}`;
  const foot =
    isCountTab(tab)
      ? slot.score == null
        ? "Score —"
        : `Score ${slot.score.toFixed(1)}`
      : slot.score == null
        ? "Score —"
        : `Score ${(slot.score * 100).toFixed(1)}%`;
  return (
    <g style={{ pointerEvents: "none" }}>
      <rect
        x={tipX}
        y={tipY}
        width={tipW}
        height={tipH}
        rx={8}
        fill="#141b2c"
        stroke="#3d4a63"
        strokeWidth="1"
      />
      <text x={tipX + 10} y={tipY + 16} fill="#9aa3b5" fontSize="8" fontWeight="700" letterSpacing="0.04em">
        {`${tabLabel.toUpperCase()} · RACE ${slot.race_number}`}
      </text>
      <text x={tipX + 10} y={tipY + 34} fill="#ffffff" fontSize="12" fontWeight="800">
        {value}
      </text>
      <text x={tipX + 10} y={tipY + 52} fill="#9aa3b5" fontSize="10" fontWeight="600">
        {foot}
      </text>
    </g>
  );
}
