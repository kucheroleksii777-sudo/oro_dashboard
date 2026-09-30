import { useEffect, useState } from "react";
import AppBar from "@mui/material/AppBar";
import Box from "@mui/material/Box";
import Toolbar from "@mui/material/Toolbar";
import Typography from "@mui/material/Typography";
import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";

import HeaderStats from "./HeaderStats";
import { useNetworkStats } from "./useNetworkStats";
import { fallbackSite, fetchSiteConfig, type SiteConfig } from "./api";
import DocsPage from "./pages/DocsPage";
import HomePage from "./pages/HomePage";
import KeysPage from "./pages/KeysPage";
import MyAgentsPage from "./pages/MyAgentsPage";
import AutoSubPage from "./pages/AutoSubPage";
import OverallPage from "./pages/OverallPage";
import RegPage from "./pages/RegPage";

function tabValue(pathname: string): string {
  if (pathname.startsWith("/docs")) {
    return "/docs";
  }
  if (pathname.startsWith("/keys")) {
    return "/keys";
  }
  if (pathname.startsWith("/reg")) {
    return "/reg";
  }
  if (pathname.startsWith("/agents")) {
    return "/agents";
  }
  if (pathname.startsWith("/overall")) {
    return "/overall";
  }
  if (pathname.startsWith("/auto-sub")) {
    return "/auto-sub";
  }
  return "/";
}

function tabLabel(site: SiteConfig, id: string): string {
  return site.tabs.find((tab) => tab.id === id)?.label ?? "";
}

function Shell({ site }: { site: SiteConfig }) {
  const location = useLocation();
  const currentTab = tabValue(location.pathname);
  const { regTao, alphaTao, taoUsd, refreshing, refreshPrices } = useNetworkStats();
  const keysLabel = tabLabel(site, "keys");

  return (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <AppBar position="static">
        <Toolbar
          disableGutters
          sx={{
            justifyContent: "flex-start",
            alignItems: "center",
            gap: 2,
            minHeight: 48,
            px: 1.5,
          }}
        >
          <Box
            component={Link}
            to="/"
            sx={{
              display: "flex",
              alignItems: "flex-end",
              gap: 1,
              textDecoration: "none",
            }}
          >
            <Box
              component="img"
              src="/oro-icon.png"
              alt=""
              sx={{ width: 40, height: 40, display: "block" }}
            />
            <Box
              sx={{
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                lineHeight: 1,
              }}
            >
              <Typography
                sx={{
                  color: "#ffffff",
                  fontSize: "1.5rem",
                  fontWeight: 700,
                  letterSpacing: "0.08em",
                  lineHeight: 1.1,
                }}
              >
                {site.brand}
              </Typography>
              <Typography
                sx={{
                  color: "#8a8f98",
                  fontSize: "0.85rem",
                  fontWeight: 400,
                  letterSpacing: "0.02em",
                  lineHeight: 1.15,
                  textAlign: "center",
                }}
              >
                miner Po
              </Typography>
            </Box>
          </Box>
          <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
            {site.tabs.map((tab) => {
              const selected = currentTab === tab.path;
              return (
                <Box
                  key={tab.id}
                  component={Link}
                  to={tab.path}
                  sx={{
                    px: 2,
                    py: 1,
                    minHeight: 36,
                    display: "flex",
                    alignItems: "center",
                    color: selected ? "#e89b25" : "#8a8f98",
                    backgroundColor: selected ? "#1c232b" : "transparent",
                    borderRadius: "6px 6px 0 0",
                    borderBottom: selected
                      ? "3px solid #e89b25"
                      : "3px solid transparent",
                    fontSize: "0.9rem",
                    fontWeight: 500,
                    textDecoration: "none",
                  }}
                >
                  {tab.label}
                </Box>
              );
            })}
          </Box>
          <HeaderStats
            regTao={regTao}
            alphaTao={alphaTao}
            taoUsd={taoUsd}
            refreshing={refreshing}
            onRefresh={refreshPrices}
          />
        </Toolbar>
      </AppBar>
      <Box
        component="main"
        sx={{ flex: 1, minHeight: 0, backgroundColor: "#0b0e12" }}
      >
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/agents" element={<MyAgentsPage />} />
          <Route path="/overall" element={<OverallPage />} />
          <Route path="/auto-sub" element={<AutoSubPage />} />
          <Route path="/race" element={<Navigate to="/overall" replace />} />
          <Route path="/reg" element={<RegPage regTao={regTao} keysLabel={keysLabel} />} />
          <Route path="/keys" element={<KeysPage />} />
          <Route path="/docs" element={<DocsPage docsUrl={site.docs_url} />} />
        </Routes>
      </Box>
    </Box>
  );
}

export default function App() {
  const [site, setSite] = useState<SiteConfig>(fallbackSite);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      const next = await fetchSiteConfig();
      if (cancelled) {
        return;
      }
      setSite((prev) =>
        prev && JSON.stringify(prev) === JSON.stringify(next) ? prev : next,
      );
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  return <Shell site={site} />;
}
