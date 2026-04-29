import './globals.css';
import { Inter, Space_Grotesk } from 'next/font/google';

const inter = Inter({ subsets: ['latin'], variable: '--font-inter' });
const spaceGrotesk = Space_Grotesk({ subsets: ['latin'], variable: '--font-space' });

export const metadata = {
  title: 'Orientation IA',
  description: 'Signaux, risque et validation MT5.',
  manifest: '/manifest.webmanifest',
  appleWebApp: { capable: true, title: 'Orientation IA' }
};

export const viewport = {
  themeColor: '#06080d'
};

export default function RootLayout({ children }) {
  return (
    <html lang="fr">
      <body className={`${inter.variable} ${spaceGrotesk.variable}`}>{children}</body>
    </html>
  );
}
