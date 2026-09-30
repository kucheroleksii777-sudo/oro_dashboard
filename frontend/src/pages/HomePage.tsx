import Box from "@mui/material/Box";

import CurrentRaceTable from "./CurrentRaceTable";

export default function HomePage() {
  return (
    <Box
      sx={{
        height: "100%",
        overflow: "auto",
        px: { xs: 1.5, md: 2 },
        pt: { xs: 1.35, md: 1.5 },
        pb: { xs: 1.5, md: 2 },
      }}
    >
      <CurrentRaceTable />
    </Box>
  );
}
