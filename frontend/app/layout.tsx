import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'LogicLens - PLC Ladder Logic Analyzer',
  description: 'AI-Powered PLC Ladder Logic Analyzer & Debugger',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
