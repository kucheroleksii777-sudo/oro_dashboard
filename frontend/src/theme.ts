import { createTheme } from "@mui/material/styles";

const theme = createTheme({
  palette: {
    mode: "dark",
    primary: {
      main: "#e89b25",
    },
    background: {
      default: "#0b0e12",
      paper: "#12171d",
    },
    text: {
      primary: "#ffffff",
      secondary: "#8a8f98",
    },
  },
  typography: {
    fontFamily:
      'system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
    button: {
      textTransform: "none",
    },
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        html: { height: "100%" },
        body: {
          height: "100%",
          margin: 0,
          backgroundColor: "#0b0e12",
        },
        "#root": { height: "100%" },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          backgroundColor: "#12171d",
          backgroundImage: "none",
          boxShadow: "none",
          borderBottom: "1px solid #2a3038",
        },
      },
    },
    MuiToolbar: {
      styleOverrides: {
        root: {
          minHeight: "48px",
          paddingLeft: "12px",
          paddingRight: "16px",
        },
      },
    },
    MuiTabs: {
      styleOverrides: {
        root: {
          minHeight: 36,
        },
        indicator: {
          height: 3,
          backgroundColor: "#e89b25",
        },
      },
    },
    MuiCheckbox: {
      styleOverrides: {
        root: {
          color: "#8a8f98",
          "&.Mui-checked": {
            color: "#3ecf8e",
          },
          "&.Mui-checked:hover": {
            color: "#3ecf8e",
          },
        },
      },
    },
    MuiTab: {
      styleOverrides: {
        root: {
          minHeight: 36,
          minWidth: 0,
          padding: "8px 16px",
          marginRight: 4,
          fontSize: "0.9rem",
          fontWeight: 500,
          color: "#8a8f98",
          opacity: 1,
          borderRadius: "6px 6px 0 0",
          "&.Mui-selected": {
            color: "#e89b25",
            backgroundColor: "#1c232b",
          },
        },
      },
    },
  },
});

export default theme;
