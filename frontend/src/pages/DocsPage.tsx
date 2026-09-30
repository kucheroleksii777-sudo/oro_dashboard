import Box from "@mui/material/Box";

type DocsPageProps = {
  docsUrl: string;
};

export default function DocsPage({ docsUrl }: DocsPageProps) {
  return (
    <Box
      component="iframe"
      src={docsUrl}
      title="ORO Documentation"
      sx={{
        display: "block",
        width: "100%",
        height: "100%",
        border: 0,
      }}
    />
  );
}
