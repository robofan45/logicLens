import { RouterProvider, createBrowserRouter, createHashRouter } from "react-router";
import { routes } from "./routes";
import { STANDALONE } from "./lib/runtime";

// The standalone file (opened from disk) and hosted copies use #/analyzer-style URLs, because
// they cannot rely on a server that rewrites every path to index.html.
const router = STANDALONE ? createHashRouter(routes) : createBrowserRouter(routes);

export default function App() {
  return <RouterProvider router={router} />;
}
