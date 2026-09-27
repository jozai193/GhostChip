import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "GhostChip — test drivers before hardware",
  description: "A reviewed virtual peripheral that runs real embedded driver code.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
