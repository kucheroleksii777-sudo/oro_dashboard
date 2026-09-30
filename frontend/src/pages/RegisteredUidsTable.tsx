import { useEffect, useMemo, useState } from "react";
import Check from "@mui/icons-material/Check";
import ContentCopy from "@mui/icons-material/ContentCopy";
import KeyboardArrowLeft from "@mui/icons-material/KeyboardArrowLeft";
import KeyboardArrowRight from "@mui/icons-material/KeyboardArrowRight";
import Close from "@mui/icons-material/Close";
import Search from "@mui/icons-material/Search";
import UnfoldMore from "@mui/icons-material/UnfoldMore";
import Box from "@mui/material/Box";
import IconButton from "@mui/material/IconButton";
import InputAdornment from "@mui/material/InputAdornment";
import TextField from "@mui/material/TextField";
import MenuItem from "@mui/material/MenuItem";
import Select from "@mui/material/Select";
import Tooltip from "@mui/material/Tooltip";
import { useMyMiners } from "../myKeys";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";

import { type RegisteredUid } from "../api";

const mono =
  'ui-monospace, "SFMono-Regular", "Cascadia Mono", "Roboto Mono", Menlo, Consolas, monospace';

const PAGE_BLUE = "#8b9bb4";
const ROW_OPTIONS = [10, 25, 50];
const FILTER_ON = "#3ecf8e";

const cellSx = {
  color: "#c5c9d0",
  borderColor: "#2a3038",
  fontSize: "0.82rem",
  py: 1.7,
  px: 1.25,
  whiteSpace: "nowrap",
} as const;

const headSx = {
  ...cellSx,
  color: "#8a8f98",
  fontWeight: 600,
  backgroundColor: "#161b22",
  py: 1.35,
} as const;

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

function shortKey(value: string): string {
  if (value.length <= 12) {
    return value || "—";
  }
  return `${value.slice(0, 5)}…${value.slice(-5)}`;
}

async function copyToClipboard(value: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch {
    const area = document.createElement("textarea");
    area.value = value;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.left = "-9999px";
    document.body.appendChild(area);
    area.select();
    area.setSelectionRange(0, value.length);
    const ok = document.execCommand("copy");
    document.body.removeChild(area);
    return ok;
  }
}

function CopyableKey({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    if (!value) {
      return;
    }
    const ok = await copyToClipboard(value);
    if (!ok) {
      return;
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  };

  return (
    <Box sx={{ display: "inline-flex", alignItems: "center", gap: 0.6 }}>
      <Box component="span" title={value}>
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

function formatEmission(value: number): string {
  if (!Number.isFinite(value) || value === 0) {
    return "0";
  }
  return value.toLocaleString("en-US", { maximumFractionDigits: 5 });
}

function formatRegistered(value: string | null): string {
  if (!value) {
    return "—";
  }
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(new Date(value));
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")} ${get("hour")}:${get("minute")}`;
}

function TablePager({
  page,
  pageCount,
  rowsPerPage,
  onPageChange,
  onRowsPerPageChange,
}: {
  page: number;
  pageCount: number;
  rowsPerPage: number;
  onPageChange: (next: number) => void;
  onRowsPerPageChange: (next: number) => void;
}) {
  const current = page + 1;
  const items = pageItems(current, Math.max(pageCount, 1));

  return (
    <Box
      sx={{
        display: "grid",
        gridTemplateColumns: "1fr auto 1fr",
        alignItems: "center",
        gap: 2,
        px: 1.5,
        py: 1.1,
        borderTop: "1px solid #2a3038",
      }}
    >
      <Box />
      <Box sx={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 1.25 }}>
        <Box
          component="button"
          type="button"
          disabled={page <= 0}
          onClick={() => onPageChange(page - 1)}
          sx={{
            display: "flex",
            border: 0,
            background: "none",
            p: 0,
            color: page <= 0 ? "#4a5058" : "#f3f4f6",
            cursor: page <= 0 ? "default" : "pointer",
          }}
        >
          <KeyboardArrowLeft fontSize="small" />
        </Box>
        {items.map((item, index) =>
          item === "ellipsis" ? (
            <Box key={`e-${index}`} sx={{ color: "#c5c9d0", fontSize: "0.85rem", px: 0.25 }}>
              …
            </Box>
          ) : (
            <Box
              key={item}
              component="button"
              type="button"
              onClick={() => onPageChange(item - 1)}
              sx={{
                minWidth: 28,
                height: 28,
                px: 0.75,
                border: 0,
                borderRadius: "5px",
                backgroundColor: item === current ? "#2a3038" : "transparent",
                color: item === current ? "#ffffff" : PAGE_BLUE,
                fontSize: "0.85rem",
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
          disabled={page >= pageCount - 1}
          onClick={() => onPageChange(page + 1)}
          sx={{
            display: "flex",
            border: 0,
            background: "none",
            p: 0,
            color: page >= pageCount - 1 ? "#4a5058" : "#f3f4f6",
            cursor: page >= pageCount - 1 ? "default" : "pointer",
          }}
        >
          <KeyboardArrowRight fontSize="small" />
        </Box>
      </Box>
      <Box sx={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 1 }}>
        <Typography sx={{ color: "#8a8f98", fontSize: "0.82rem" }}>Show rows</Typography>
        <Select
          size="small"
          value={rowsPerPage}
          onChange={(event) => onRowsPerPageChange(Number(event.target.value))}
          IconComponent={UnfoldMore}
          sx={{
            color: PAGE_BLUE,
            fontSize: "0.82rem",
            height: 30,
            "& .MuiOutlinedInput-notchedOutline": { borderColor: "#3a424c" },
            "&:hover .MuiOutlinedInput-notchedOutline": { borderColor: "#4a525c" },
            "&.Mui-focused .MuiOutlinedInput-notchedOutline": { borderColor: "#4a525c" },
            "& .MuiSelect-select": { py: 0.5, pr: 3, pl: 1.1 },
            "& .MuiSelect-icon": { color: "#8a8f98", right: 4 },
          }}
          MenuProps={{
            PaperProps: {
              sx: { backgroundColor: "#161b22", color: "#f3f4f6", border: "1px solid #2a3038" },
            },
          }}
        >
          {ROW_OPTIONS.map((option) => (
            <MenuItem key={option} value={option} sx={{ fontSize: "0.82rem" }}>
              {option}
            </MenuItem>
          ))}
        </Select>
      </Box>
    </Box>
  );
}

export default function UidTable({
  title,
  rows,
  loading,
  keysLabel,
}: {
  title: string;
  rows: RegisteredUid[];
  loading: boolean;
  keysLabel: string;
}) {
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(10);
  const [query, setQuery] = useState("");
  const [otherNickname, setOtherNickname] = useState("");
  const { isOtherNickname, otherNicknames } = useMyMiners();
  const onlyOther = Boolean(otherNickname);

  useEffect(() => {
    setPage(0);
  }, [title, rowsPerPage, query, otherNickname]);

  const filteredRows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return rows.filter((row) => {
      if (onlyOther && !isOtherNickname(otherNickname, row.hotkey, row.coldkey)) {
        return false;
      }
      if (!needle) {
        return true;
      }
      return (
        String(row.uid).includes(needle) ||
        row.hotkey.toLowerCase().includes(needle) ||
        row.coldkey.toLowerCase().includes(needle)
      );
    });
  }, [isOtherNickname, onlyOther, otherNickname, query, rows]);

  const pageRows = useMemo(() => {
    const start = page * rowsPerPage;
    return filteredRows.slice(start, start + rowsPerPage);
  }, [filteredRows, page, rowsPerPage]);

  return (
    <Box
      sx={{
        backgroundColor: "#12171d",
        border: "1px solid #2a3038",
        borderRadius: "10px",
        overflow: "hidden",
      }}
    >
      <Box
        sx={{
          px: 1.5,
          py: 1.1,
          borderBottom: "1px solid #2a3038",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          columnGap: 1.25,
          rowGap: 1,
        }}
      >
        <Typography
          sx={{
            color: "#f3f4f6",
            fontSize: "0.95rem",
            fontWeight: 600,
            flex: "0 1 auto",
            minWidth: 0,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {title}
        </Typography>
        <Box
          sx={{
            display: "flex",
            alignItems: "center",
            gap: 1.25,
            flex: "0 0 auto",
            ml: "auto",
            minWidth: "max-content",
          }}
        >
        <TextField
          size="small"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search UID / hotkey / coldkey"
          slotProps={{
            input: {
              startAdornment: (
                <InputAdornment position="start">
                  <Search sx={{ fontSize: 16, color: "#8a8f98" }} />
                </InputAdornment>
              ),
              endAdornment: (
                <InputAdornment position="end">
                  <IconButton
                    size="small"
                    aria-label="Clear search"
                    onClick={() => setQuery("")}
                    disabled={!query}
                    sx={{
                      color: query ? "#8a8f98" : "#4a5058",
                      p: 0.25,
                      visibility: "visible",
                      "&:hover": { color: "#c5c9d0" },
                    }}
                  >
                    <Close sx={{ fontSize: 15 }} />
                  </IconButton>
                </InputAdornment>
              ),
            },
          }}
          sx={{
            width: 300,
            minWidth: 300,
            maxWidth: 300,
            flexShrink: 0,
            "& .MuiOutlinedInput-root": {
              height: 32,
              color: "#f3f4f6",
              fontSize: "0.78rem",
              fontFamily: mono,
              backgroundColor: "#1c1f26",
              pr: 0.5,
              "& fieldset": { borderColor: "#2e343c", borderWidth: "1px !important" },
              "&:hover fieldset": { borderColor: "#3a424c" },
              "&.Mui-focused fieldset": { borderColor: FILTER_ON },
            },
            "& .MuiOutlinedInput-input": { py: 0.5 },
          }}
        />
        <Select
          displayEmpty
          size="small"
          value={otherNickname}
          onChange={(event) => setOtherNickname(String(event.target.value))}
          renderValue={(value) => (value ? String(value) : "All")}
          MenuProps={{
            PaperProps: {
              sx: {
                backgroundColor: "#12171d",
                border: "1px solid #2a3038",
                backgroundImage: "none",
              },
            },
          }}
          sx={{
            width: 140,
            height: 32,
            flexShrink: 0,
            color: otherNickname ? FILTER_ON : "#4a5058",
            fontSize: "0.82rem",
            fontWeight: 600,
            backgroundColor: "#1c1f26",
            "& .MuiOutlinedInput-notchedOutline": { borderColor: "#2e343c" },
            "&:hover .MuiOutlinedInput-notchedOutline": { borderColor: "#2e343c" },
            "&.Mui-focused .MuiOutlinedInput-notchedOutline": { borderColor: "#2e343c" },
            "& .MuiSelect-icon": { color: otherNickname ? FILTER_ON : "#4a5058" },
            "&.Mui-disabled": {
              color: "#4a5058",
              "& .MuiOutlinedInput-notchedOutline": { borderColor: "#2e343c" },
              "& .MuiSelect-icon": { color: "#4a5058" },
            },
          }}
        >
          <MenuItem value="" sx={{ fontSize: "0.82rem" }}>
            All
          </MenuItem>
          {otherNicknames.map((name) => (
            <MenuItem key={name} value={name} sx={{ fontSize: "0.82rem" }}>
              {name}
            </MenuItem>
          ))}
        </Select>
        </Box>
      </Box>
      <TableContainer>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell sx={headSx}>#</TableCell>
              <TableCell sx={headSx}>UID</TableCell>
              <TableCell sx={headSx}>Hotkey</TableCell>
              <TableCell sx={headSx}>Coldkey</TableCell>
              <TableCell sx={{ ...headSx, textAlign: "right" }}>Emission</TableCell>
              <TableCell sx={headSx}>Registered</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={6} sx={{ ...cellSx, color: "#8a8f98" }}>
                  Loading UIDs…
                </TableCell>
              </TableRow>
            ) : !filteredRows.length ? (
              <TableRow>
                <TableCell colSpan={6} sx={{ ...cellSx, color: "#8a8f98" }}>
                  {onlyOther
                    ? `No matching keys. Add a coldkey on the ${keysLabel} tab.`
                    : query.trim()
                      ? "No matching UID / hotkey / coldkey"
                      : "No registered UIDs"}
                </TableCell>
              </TableRow>
            ) : (
              pageRows.map((row, index) => (
                <TableRow key={`${row.uid}-${row.hotkey}`} hover>
                  <TableCell sx={cellSx}>{page * rowsPerPage + index + 1}</TableCell>
                  <TableCell
                    sx={{ ...cellSx, color: "#3ecf8e", fontFamily: mono, fontWeight: 600 }}
                  >
                    {row.uid}
                  </TableCell>
                  <TableCell sx={{ ...cellSx, fontFamily: mono }}>
                    <CopyableKey value={row.hotkey} />
                  </TableCell>
                  <TableCell sx={{ ...cellSx, fontFamily: mono }}>
                    <CopyableKey value={row.coldkey} />
                  </TableCell>
                  <TableCell sx={{ ...cellSx, fontFamily: mono, textAlign: "right" }}>
                    {formatEmission(row.emission)}
                  </TableCell>
                  <TableCell sx={{ ...cellSx, fontFamily: mono }}>
                    {formatRegistered(row.registered_at)}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </TableContainer>
      <TablePager
        page={page}
        pageCount={Math.max(1, Math.ceil(filteredRows.length / rowsPerPage))}
        rowsPerPage={rowsPerPage}
        onPageChange={setPage}
        onRowsPerPageChange={(next) => {
          setRowsPerPage(next);
          setPage(0);
        }}
      />
    </Box>
  );
}
