import "./globals.css";

export const metadata = {
  title: "Playlist2Album",
  description: "Download YouTube playlists as MP3 albums with metadata",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        {children}
      </body>
    </html>
  );
}

