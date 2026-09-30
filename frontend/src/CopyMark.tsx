import { useState } from "react";
import Check from "@mui/icons-material/Check";
import MenuBook from "@mui/icons-material/MenuBook";
import Box from "@mui/material/Box";

export function submitCommand(agentName: string, hotkeyName: string): string {
  const name = agentName.replace(/"/g, '\\"');
  return [
    "oro submit \\",
    `--agent-name "${name}" \\`,
    "--agent-file src/po/work/agent.py \\",
    "--wallet-name PoWallet \\",
    `--wallet-hotkey ${hotkeyName}`,
  ].join("\n");
}

export function CopyMark({ value }: { value: string }) {
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

  if (!value) {
    return null;
  }

  return (
    <Box
      component="button"
      type="button"
      aria-label="Copy"
      onClick={() => {
        void copy();
      }}
      sx={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: 22,
        height: 22,
        border: "1px solid",
        borderColor: "#4a5563",
        borderRadius: "4px",
        background: "none",
        p: 0,
        color: copied ? "#4ea1ff" : "#e85d75",
        cursor: "pointer",
        "&:hover": {
          color: copied ? "#4ea1ff" : "#e85d75",
          borderColor: "#e89b25",
        },
      }}
    >
      {copied ? <Check sx={{ fontSize: 13 }} /> : <MenuBook sx={{ fontSize: 13 }} />}
    </Box>
  );
}
