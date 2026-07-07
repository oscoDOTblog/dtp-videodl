import "./globals.css";

export const metadata = {
  title: "VideoDL",
  description: "Download playlists and tracks from supported sites as tagged MP3 albums",
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

