import "./globals.css";
import AuthWrapper from "../components/AuthWrapper";
import AppShell from "../components/AppShell";

export const metadata = {
  title: "VideoDL",
  description: "Download playlists and tracks into DTP Tunes",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <AuthWrapper>
          <AppShell>{children}</AppShell>
        </AuthWrapper>
      </body>
    </html>
  );
}
