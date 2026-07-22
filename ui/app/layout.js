import "./globals.css";
import AppHeader from "../components/AppHeader";

export const metadata = {
  title: "VideoDL",
  description: "Download playlists and tracks into DTP Tunes",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <AppHeader />
        {children}
      </body>
    </html>
  );
}
