import { Link } from "react-router";

export function NotFound() {
  return (
    <div className="max-w-xl mx-auto px-4 py-24 text-center">
      <h1 className="text-slate-100" style={{ fontSize: "1.3rem", fontWeight: 700 }}>Page not found</h1>
      <p className="mt-2 text-slate-400" style={{ fontSize: "0.88rem" }}>That address doesn't exist in LogicLens.</p>
      <Link to="/analyzer" className="mt-4 inline-block text-cyan-300 hover:text-cyan-200">Open the analyzer</Link>
    </div>
  );
}
