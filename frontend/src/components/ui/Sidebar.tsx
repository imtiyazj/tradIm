"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { UserButton } from "@clerk/nextjs";

const NAV = [
  { href: "/dashboard",            label: "Overview",   icon: "◈" },
  { href: "/dashboard/discover",   label: "Discover",   icon: "◉" },
  { href: "/dashboard/signals",    label: "Signals",    icon: "◎" },
  { href: "/dashboard/watchlist",  label: "Watchlist",  icon: "◇" },
  { href: "/dashboard/portfolio",  label: "Portfolio",  icon: "◆" },
  { href: "/dashboard/reports",    label: "Reports",    icon: "▤" },
  { href: "/dashboard/tax",        label: "Tax",        icon: "◻" },
];

export default function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="sidebar">
      {/* Logo */}
      <div className="nav-logo">
        <div className="nav-logo-text">◆ HALAL TRADER</div>
        <div className="nav-logo-sub">Shariah-compliant research</div>
      </div>

      {/* Nav */}
      <div className="nav-section">Navigation</div>
      {NAV.map((item) => (
        <Link
          key={item.href}
          href={item.href}
          className={`nav-item ${pathname === item.href ? "active" : ""}`}
        >
          <span style={{ fontFamily: "var(--mono)", fontSize: "14px" }}>
            {item.icon}
          </span>
          {item.label}
        </Link>
      ))}

      {/* Spacer + User */}
      <div style={{ flex: 1 }} />
      <div style={{
        padding: "16px 20px",
        borderTop: "1px solid var(--border)",
        display: "flex",
        alignItems: "center",
        gap: "10px",
      }}>
        <UserButton
          appearance={{
            variables: { colorPrimary: "#00c896" },
            elements: { avatarBox: { width: 28, height: 28 } },
          }}
        />
        <span style={{ fontSize: "12px", color: "var(--text2)", fontFamily: "var(--mono)" }}>
          Account
        </span>
      </div>
    </aside>
  );
}
