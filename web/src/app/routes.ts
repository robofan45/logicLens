import type { RouteObject } from "react-router";
import { Layout } from "./components/Layout";
import { Analyzer } from "./pages/Analyzer";
import { Docs } from "./pages/Docs";
import { History } from "./pages/History";
import { Home } from "./pages/Home";
import { NotFound } from "./pages/NotFound";

export const routes: RouteObject[] = [
  {
    path: "/",
    Component: Layout,
    children: [
      { index: true, Component: Home },
      { path: "analyzer", Component: Analyzer },
      { path: "history", Component: History },
      { path: "docs", Component: Docs },
      { path: "*", Component: NotFound },
    ],
  },
];
