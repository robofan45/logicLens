import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router";
import { BookOpen, ChevronLeft, ChevronRight, Cpu, History, Home, Menu, X } from "lucide-react";
import { useBackend } from "../lib/useBackend";
import iconUrl from "../../assets/icon.svg";
import { STANDALONE } from "../lib/runtime";

const NAV = [
  { path: "/", label: "Home", icon: <Home size={18} aria-hidden /> },
  { path: "/analyzer", label: "Analyzer", icon: <Cpu size={18} aria-hidden /> },
  { path: "/history", label: "History", icon: <History size={18} aria-hidden /> },
  { path: "/docs", label: "Docs", icon: <BookOpen size={18} aria-hidden /> },
];

function ServerStatus({ collapsed }: { collapsed: boolean }) {
  const b = useBackend();
  const color = b.status === "online" ? "bg-emerald-400" : b.status === "offline" ? "bg-slate-500" : "bg-amber-400";
  const text =
    b.status === "online"
      ? `Server online${b.meta ? ` · vision ${b.meta.engines.active ? "on" : "off"} · AI ${b.meta.llm.enabled ? "on" : "off"}` : ""}`
      : b.status === "offline"
        ? STANDALONE ? "Standalone copy · text analysis only" : "Server offline · local analysis only"
        : "Checking server…";
  return (
    <div className="flex items-center gap-2 px-3 py-2 text-slate-500" style={{ fontSize: "0.7rem" }} title={text} role="status">
      <span className={`w-2 h-2 rounded-full flex-shrink-0 ${color}`} aria-hidden />
      {!collapsed && <span className="truncate">{text}</span>}
      {collapsed && <span className="sr-only">{text}</span>}
    </div>
  );
}

export function Layout() {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();

  useEffect(() => setMobileOpen(false), [location.pathname]);
  useEffect(() => {
    const titles: Record<string, string> = { "/": "LogicLens", "/analyzer": "Analyzer · LogicLens", "/history": "History · LogicLens", "/docs": "Docs · LogicLens" };
    document.title = titles[location.pathname] ?? "LogicLens";
  }, [location.pathname]);

  const nav = (
    <nav className="flex-1 px-2 py-4 space-y-1" aria-label="Main">
      {NAV.map((item) => (
        <NavLink
          key={item.path}
          to={item.path}
          end={item.path === "/"}
          className={({ isActive }) =>
            `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500 ${
              isActive ? "bg-cyan-500/10 text-cyan-300 border border-cyan-500/20" : "text-slate-400 hover:bg-slate-800 hover:text-slate-200 border border-transparent"
            }`
          }
          title={collapsed ? item.label : undefined}
        >
          {item.icon}
          {!collapsed && <span style={{ fontSize: "0.875rem", whiteSpace: "nowrap" }}>{item.label}</span>}
          {collapsed && <span className="sr-only">{item.label}</span>}
        </NavLink>
      ))}
    </nav>
  );

  const brand = (
    <div className="flex items-center gap-3 px-4 py-5 border-b border-slate-800">
      <img src={iconUrl} alt="" width={32} height={32} className="flex-shrink-0 rounded-lg" />
      {!collapsed && (
        <div>
          <span className="text-cyan-400" style={{ fontSize: "1.05rem", fontWeight: 700, letterSpacing: "-0.02em" }}>
            Logic<span className="text-white">Lens</span>
          </span>
          <div className="text-slate-500" style={{ fontSize: "0.62rem", letterSpacing: "0.08em", textTransform: "uppercase" }}>PLC logic analyzer · v2</div>
        </div>
      )}
    </div>
  );

  return (
    <div className="flex h-screen bg-slate-950 text-slate-100 overflow-hidden">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[60] focus:px-3 focus:py-2 focus:rounded-lg focus:bg-cyan-500 focus:text-slate-950">
        Skip to content
      </a>

      {/* desktop sidebar */}
      <aside
        className="hidden lg:flex flex-col bg-slate-900 border-r border-slate-800 transition-[width] duration-200"
        style={{ width: collapsed ? 68 : 228 }}
      >
        {brand}
        {nav}
        <div className="px-2 py-3 border-t border-slate-800 space-y-1">
          <ServerStatus collapsed={collapsed} />
          <button
            type="button"
            onClick={() => setCollapsed((c) => !c)}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className="flex items-center gap-3 px-3 py-2 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-800 w-full"
          >
            {collapsed ? <ChevronRight size={18} aria-hidden /> : <ChevronLeft size={18} aria-hidden />}
            {!collapsed && <span style={{ fontSize: "0.85rem" }}>Collapse</span>}
          </button>
        </div>
      </aside>

      {/* mobile drawer */}
      {mobileOpen && (
        <div className="lg:hidden fixed inset-0 z-50 flex">
          <div className="absolute inset-0 bg-black/60" onClick={() => setMobileOpen(false)} aria-hidden />
          <aside className="relative w-64 h-full flex flex-col bg-slate-900 border-r border-slate-800" aria-label="Menu">
            <button type="button" onClick={() => setMobileOpen(false)} aria-label="Close menu" className="absolute top-4 right-3 p-2 rounded-lg text-slate-400 hover:bg-slate-800">
              <X size={18} aria-hidden />
            </button>
            {brand}
            {nav}
            <div className="px-2 py-3 border-t border-slate-800"><ServerStatus collapsed={false} /></div>
          </aside>
        </div>
      )}

      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="lg:hidden flex items-center gap-3 px-4 py-3 bg-slate-900 border-b border-slate-800">
          <button type="button" onClick={() => setMobileOpen(true)} aria-label="Open menu" aria-expanded={mobileOpen} className="p-2 rounded-lg text-slate-400 hover:bg-slate-800">
            <Menu size={20} aria-hidden />
          </button>
          <img src={iconUrl} alt="" width={24} height={24} className="rounded" />
          <span className="text-cyan-400" style={{ fontWeight: 700 }}>
            Logic<span className="text-white">Lens</span>
          </span>
        </div>
        <main id="main" className="flex-1 overflow-y-auto focus:outline-none" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
