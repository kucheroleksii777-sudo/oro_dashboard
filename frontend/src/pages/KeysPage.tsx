import { useEffect, useState } from "react";
import Check from "@mui/icons-material/Check";
import Close from "@mui/icons-material/Close";
import ContentCopy from "@mui/icons-material/ContentCopy";
import Edit from "@mui/icons-material/Edit";
import KeyboardArrowUp from "@mui/icons-material/KeyboardArrowUp";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import FormControl from "@mui/material/FormControl";
import IconButton from "@mui/material/IconButton";
import MenuItem from "@mui/material/MenuItem";
import Popover from "@mui/material/Popover";
import Select from "@mui/material/Select";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";
import { HexColorPicker } from "react-colorful";

import type { SavedColdKey, SavedKeyKind } from "../api";
import { KEY_COLORS, nextKeyColor, uniqueKeyColor } from "../api";
import { reloadKeys, useMyMiners } from "../myKeys";

const mono =
  'ui-monospace, "SFMono-Regular", "Cascadia Mono", "Roboto Mono", Menlo, Consolas, monospace';

const cellSx = {
  color: "#c5c9d0",
  borderColor: "#2a3038",
  fontSize: "0.8rem",
  lineHeight: 1.3,
  py: 1.15,
  px: 1.15,
  whiteSpace: "nowrap",
} as const;

const headSx = {
  ...cellSx,
  color: "#8a8f98",
  fontWeight: 600,
  backgroundColor: "#161b22",
  py: 0.95,
} as const;

const fieldSx = {
  "& .MuiOutlinedInput-root": {
    height: 36,
    color: "#f3f4f6",
    fontSize: "0.8rem",
    backgroundColor: "#1c1f26",
    "& fieldset": { borderColor: "#2e343c" },
    "&:hover fieldset": { borderColor: "#3a424c" },
    "&.Mui-focused fieldset": { borderColor: "#4ea1ff" },
  },
  "& .MuiFormHelperText-root": { mx: 0, minHeight: 20 },
} as const;

const addButtonSx = {
  height: 36,
  px: 2,
  backgroundColor: "transparent",
  color: "#4ea1ff",
  border: "1px solid #4ea1ff",
  fontWeight: 700,
  boxShadow: "none",
  "&:hover": {
    backgroundColor: "transparent",
    color: "#4ea1ff",
    border: "1px solid #4ea1ff",
    boxShadow: "none",
  },
} as const;

const dialogPaperSx = {
  backgroundColor: "#12171d",
  border: "1px solid #2a3038",
  backgroundImage: "none",
} as const;

function ColorPan({
  color,
  onChange,
}: {
  color: string;
  onChange: (value: string) => void;
}) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const [hex, setHex] = useState(color);

  useEffect(() => {
    setHex(color);
  }, [color]);

  const applyHex = (value: string) => {
    const next = value.startsWith("#") ? value : `#${value}`;
    setHex(next);
    if (/^#[0-9a-fA-F]{6}$/.test(next)) {
      onChange(next.toLowerCase());
    }
  };

  return (
    <>
      <Box sx={{ display: "flex", alignItems: "center", gap: 1.25 }}>
        <Box
          component="button"
          type="button"
          aria-label="Color"
          onClick={(event) => setAnchor(event.currentTarget)}
          sx={{
            width: 36,
            height: 36,
            p: 0,
            border: "1px solid #2e343c",
            borderRadius: "8px",
            background: `linear-gradient(180deg, rgba(255,255,255,0.14), transparent 42%), ${color}`,
            cursor: "pointer",
            boxShadow: "inset 0 0 0 1px rgba(0,0,0,0.35)",
            flexShrink: 0,
          }}
        />
        <TextField
          size="small"
          value={hex}
          onChange={(event) => applyHex(event.target.value)}
          sx={{
            ...fieldSx,
            width: 112,
            "& .MuiOutlinedInput-root": {
              ...fieldSx["& .MuiOutlinedInput-root"],
              fontFamily: mono,
            },
          }}
        />
      </Box>
      <Popover
        open={Boolean(anchor)}
        anchorEl={anchor}
        onClose={() => setAnchor(null)}
        anchorOrigin={{ vertical: "bottom", horizontal: "left" }}
        transformOrigin={{ vertical: "top", horizontal: "left" }}
        slotProps={{
          paper: {
            sx: {
              mt: 1,
              p: 1.5,
              width: 248,
              backgroundColor: "#161b22",
              border: "1px solid #2a3038",
              borderRadius: "12px",
              backgroundImage: "none",
              boxShadow: "0 16px 40px rgba(0,0,0,0.45)",
            },
          },
        }}
      >
        <Box
          sx={{
            "& .react-colorful": { width: "100%", height: 168 },
            "& .react-colorful__saturation": {
              borderRadius: "10px",
              borderBottom: "none",
            },
            "& .react-colorful__hue": {
              height: 12,
              borderRadius: "999px",
              marginTop: "14px",
            },
            "& .react-colorful__pointer": {
              width: 16,
              height: 16,
              borderWidth: 2,
            },
            "& .react-colorful__hue-pointer": {
              width: 16,
              height: 16,
              borderRadius: "50%",
            },
          }}
        >
          <HexColorPicker color={/^#[0-9a-fA-F]{6}$/.test(color) ? color : "#4ea1ff"} onChange={onChange} />
        </Box>
        <Box sx={{ mt: 1.5, display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: 0.75 }}>
          {KEY_COLORS.map((swatch) => {
            const selected = swatch === color;
            return (
              <Box
                key={swatch}
                component="button"
                type="button"
                onClick={() => onChange(swatch)}
                sx={{
                  width: "100%",
                  aspectRatio: "1",
                  p: 0,
                  borderRadius: "50%",
                  border: selected ? "2px solid #f3f4f6" : "1px solid #2e343c",
                  backgroundColor: swatch,
                  cursor: "pointer",
                  boxShadow: selected ? "0 0 0 1px #161b22 inset" : "none",
                }}
              />
            );
          })}
        </Box>
      </Popover>
    </>
  );
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

  return (
    <Box sx={{ display: "flex", alignItems: "center", gap: 0.6, minWidth: 0, maxWidth: "100%" }}>
      <Box
        component="span"
        title={value}
        sx={{
          fontFamily: mono,
          minWidth: 0,
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
      >
        {value}
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
            onClick={async () => {
              const ok = await copyToClipboard(value);
              if (!ok) {
                return;
              }
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1600);
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

function formatAdded(value: string): string {
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

const tableScrollSx = {
  overflowX: "hidden",
  overflowY: "auto",
  scrollbarWidth: "auto",
  scrollbarColor: "#4a5563 transparent",
  "&::-webkit-scrollbar": { width: 14, height: 14 },
  "&::-webkit-scrollbar-track": { backgroundColor: "transparent" },
  "&::-webkit-scrollbar-thumb": {
    backgroundColor: "#3d4654",
    borderRadius: "8px",
  },
} as const;

function KeyTable({
  rows,
  onEdit,
  onClear,
  onRaise,
}: {
  rows: SavedColdKey[];
  onEdit: (row: SavedColdKey) => void;
  onClear: (row: SavedColdKey) => void;
  onRaise?: (row: SavedColdKey) => void;
}) {
  return (
    <Box
      sx={{
        flex: 1,
        minHeight: 0,
        display: "flex",
        flexDirection: "column",
        backgroundColor: "#12171d",
        border: "1px solid #2a3038",
        borderRadius: "10px",
        overflow: "hidden",
      }}
    >
      <TableContainer sx={{ ...tableScrollSx, flex: 1, minHeight: 0 }}>
        <Table sx={{ tableLayout: "fixed", width: "100%" }} stickyHeader>
          <TableHead>
            <TableRow>
              <TableCell sx={{ ...headSx, width: 48 }}>#</TableCell>
              <TableCell sx={{ ...headSx, width: 88 }}>Type</TableCell>
              <TableCell sx={headSx}>Key</TableCell>
              <TableCell sx={{ ...headSx, width: 72, textAlign: "center" }}>Color</TableCell>
              <TableCell sx={{ ...headSx, width: 160, textAlign: "center" }}>Group</TableCell>
              <TableCell sx={{ ...headSx, width: 150 }}>Added</TableCell>
              <TableCell sx={{ ...headSx, width: onRaise ? 120 : 96 }} />
            </TableRow>
          </TableHead>
          <TableBody>
            {!rows.length ? (
              <TableRow>
                <TableCell colSpan={7} sx={{ ...cellSx, color: "#8a8f98" }}>
                  No keys registered yet.
                </TableCell>
              </TableRow>
            ) : (
              rows.map((row, index) => (
                <TableRow key={row.id} hover>
                  <TableCell sx={cellSx}>{index + 1}</TableCell>
                  <TableCell sx={cellSx}>{row.kind === "hot" ? "Hotkey" : "Coldkey"}</TableCell>
                  <TableCell sx={{ ...cellSx, overflow: "hidden" }}>
                    <CopyableKey value={row.ss58} />
                  </TableCell>
                  <TableCell sx={{ ...cellSx, textAlign: "center" }}>
                    <Box
                      sx={{
                        width: 20,
                        height: 20,
                        borderRadius: "50%",
                        backgroundColor: row.color || "#4ea1ff",
                        border: "1px solid #2a3038",
                        display: "inline-block",
                        verticalAlign: "middle",
                      }}
                    />
                  </TableCell>
                  <TableCell sx={{ ...cellSx, textAlign: "center" }}>{row.nickname}</TableCell>
                  <TableCell sx={{ ...cellSx, fontFamily: mono }}>
                    {formatAdded(row.created_at)}
                  </TableCell>
                  <TableCell sx={{ ...cellSx, width: onRaise ? 120 : 96 }}>
                    <Box sx={{ display: "inline-flex", alignItems: "center", gap: 1 }}>
                    {onRaise ? (
                    <Tooltip
                      title="rise in order"
                      placement="top"
                      arrow
                      slotProps={{
                        popper: {
                          modifiers: [
                            { name: "preventOverflow", enabled: false },
                            { name: "hide", enabled: false },
                          ],
                        },
                      }}
                    >
                      <Box component="span" sx={{ display: "inline-flex" }}>
                        <IconButton
                          size="small"
                          aria-label="Rise in order"
                          disabled={index === 0}
                          onClick={() => onRaise(row)}
                          sx={{ color: "#8a8f98", p: 0.25, "&:hover": { color: "#f3f4f6" } }}
                        >
                          <KeyboardArrowUp sx={{ fontSize: 18 }} />
                        </IconButton>
                      </Box>
                    </Tooltip>
                    ) : null}
                    <Tooltip title="edit" placement="top" arrow>
                      <IconButton
                        size="small"
                        aria-label="Edit key"
                        onClick={() => onEdit(row)}
                        sx={{ color: "#8a8f98", p: 0.25, "&:hover": { color: "#f3f4f6" } }}
                      >
                        <Edit sx={{ fontSize: 16 }} />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="clear" placement="top" arrow>
                      <IconButton
                        size="small"
                        aria-label="Clear key"
                        onClick={() => onClear(row)}
                        sx={{ color: "#8a8f98", p: 0.25, "&:hover": { color: "#f3f4f6" } }}
                      >
                        <Close sx={{ fontSize: 16 }} />
                      </IconButton>
                    </Tooltip>
                    </Box>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  );
}

export default function KeysPage() {
  const { rows, addKey, editKey, raiseKey, removeRow } = useMyMiners();
  useEffect(() => {
    void reloadKeys();
  }, []);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<SavedColdKey | null>(null);
  const [kind, setKind] = useState<SavedKeyKind>("cold");
  const [draft, setDraft] = useState("");
  const [nickname, setNickname] = useState("");
  const [color, setColor] = useState("#4ea1ff");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [pending, setPending] = useState<SavedColdKey | null>(null);
  const [clearing, setClearing] = useState(false);
  const tableRows = [...rows].sort(
    (a, b) => (a.sort ?? 0) - (b.sort ?? 0) || (Date.parse(a.created_at) || 0) - (Date.parse(b.created_at) || 0),
  );

  const closeAdd = () => {
    if (saving) {
      return;
    }
    setAdding(false);
    setEditing(null);
    setKind("cold");
    setDraft("");
    setNickname("");
    setColor(nextKeyColor(rows.map((row) => row.color)));
    setError("");
  };

  const openAdd = () => {
    setEditing(null);
    setKind("cold");
    setDraft("");
    setNickname("");
    setColor(nextKeyColor(rows.map((row) => row.color)));
    setError("");
    setAdding(true);
  };

  const openEdit = (row: SavedColdKey) => {
    setAdding(false);
    setEditing(row);
    setKind(row.kind);
    setDraft(row.ss58);
    setNickname(row.nickname);
    setColor(row.color || "#4ea1ff");
    setError("");
  };

  const submit = async () => {
    const value = draft.trim();
    if (!value) {
      setError("Paste a key.");
      return;
    }
    if (value.length < 40) {
      setError("That does not look like a full SS58 key.");
      return;
    }
    const savedColor = uniqueKeyColor(
      color,
      rows.filter((row) => row.id !== editing?.id).map((row) => row.color),
    );
    setColor(savedColor);
    setSaving(true);
    const ok = editing
      ? await editKey(editing.id, value, kind, nickname, savedColor)
      : adding
        ? await addKey(value, kind, nickname, "other", savedColor)
        : false;
    setSaving(false);
    if (!ok) {
      setError("This key is already saved, or could not be stored.");
      return;
    }
    setAdding(false);
    setEditing(null);
    setKind("cold");
    setDraft("");
    setNickname("");
    setColor(nextKeyColor(rows.map((row) => row.color)));
    setError("");
  };

  return (
    <Box
      sx={{
        height: "100%",
        minHeight: 0,
        overflow: "hidden",
        pt: { xs: 1.5, md: 2 },
        pb: { xs: 1.5, md: 2 },
        px: { xs: 2, md: 3.5, lg: 5 },
        display: "flex",
        flexDirection: "column",
        gap: 1.25,
      }}
    >
      <Box sx={{ display: "flex", justifyContent: "flex-end", flexShrink: 0 }}>
        <Button type="button" variant="contained" onClick={openAdd} sx={addButtonSx}>
          Add
        </Button>
      </Box>
      <KeyTable
        rows={tableRows}
        onEdit={openEdit}
        onClear={setPending}
        onRaise={(row) => {
          void raiseKey(row.id);
        }}
      />
      <Dialog
        open={Boolean(adding) || Boolean(editing)}
        onClose={closeAdd}
        fullWidth
        maxWidth="sm"
        disableEnforceFocus
        slotProps={{
          paper: { sx: dialogPaperSx },
        }}
      >
        <Box
          component="form"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <DialogTitle sx={{ color: "#f3f4f6", pb: 1 }}>
            {editing ? "Edit key" : "Add key"}
          </DialogTitle>
          <DialogContent sx={{ pt: 1, pb: 1, display: "flex", flexDirection: "column", gap: 1.25 }}>
            <FormControl size="small" fullWidth sx={fieldSx}>
              <Select
                value={kind}
                onChange={(event) => setKind(event.target.value as SavedKeyKind)}
                MenuProps={{
                  PaperProps: {
                    sx: {
                      backgroundColor: "#12171d",
                      border: "1px solid #2a3038",
                      backgroundImage: "none",
                    },
                  },
                }}
              >
                <MenuItem value="cold">Coldkey</MenuItem>
                <MenuItem value="hot">Hotkey</MenuItem>
              </Select>
            </FormControl>
            <TextField
              autoFocus
              fullWidth
              size="small"
              value={draft}
              onChange={(event) => {
                setDraft(event.target.value);
                if (error) {
                  setError("");
                }
              }}
              placeholder="Paste key"
              error={Boolean(error)}
              helperText={error || " "}
              sx={{ ...fieldSx, "& .MuiOutlinedInput-root": { ...fieldSx["& .MuiOutlinedInput-root"], fontFamily: mono } }}
            />
            <TextField
              fullWidth
              size="small"
              value={nickname}
              onChange={(event) => setNickname(event.target.value)}
              placeholder="Group"
              sx={fieldSx}
            />
            <ColorPan color={color} onChange={setColor} />
          </DialogContent>
          <DialogActions sx={{ px: 3, pb: 2 }}>
            <Button
              type="button"
              onClick={closeAdd}
              disabled={saving}
              sx={{ color: "#8a8f98" }}
            >
              Cancel
            </Button>
            <Button type="submit" variant="contained" disabled={saving} sx={addButtonSx}>
              {editing ? "Save" : "Add"}
            </Button>
          </DialogActions>
        </Box>
      </Dialog>
      <Dialog
        open={Boolean(pending)}
        onClose={() => {
          if (!clearing) {
            setPending(null);
          }
        }}
        fullWidth
        maxWidth="sm"
        slotProps={{
          paper: { sx: dialogPaperSx },
        }}
      >
        <DialogTitle sx={{ color: "#f3f4f6", pb: 1 }}>Clear key</DialogTitle>
        <DialogContent sx={{ pt: 1, pb: 1 }}>
          <Typography sx={{ color: "#c5c9d0", fontSize: "0.88rem", fontFamily: mono, wordBreak: "break-all" }}>
            {pending?.ss58}
          </Typography>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button
            type="button"
            onClick={() => setPending(null)}
            disabled={clearing}
            sx={{ color: "#8a8f98" }}
          >
            Cancel
          </Button>
          <Button
            type="button"
            variant="contained"
            disabled={clearing}
            onClick={async () => {
              if (!pending) {
                return;
              }
              setClearing(true);
              await removeRow(pending.id);
              setClearing(false);
              setPending(null);
            }}
            sx={addButtonSx}
          >
            Clear
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
