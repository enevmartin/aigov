// @ts-check
import { defineConfig } from "astro/config";

// Static output only — the site is a pure build-time render of ../published/.
export default defineConfig({
  output: "static",
  site: "https://aigov.bg",
});
