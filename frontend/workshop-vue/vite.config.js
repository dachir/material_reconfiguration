import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
export default defineConfig({
	plugins: [vue()],
	define: { "process.env.NODE_ENV": JSON.stringify("production") },
	build: {
		outDir: "../../mat_reco/public/js/workshop_vue_dist",
		emptyOutDir: true,
		lib: {
			entry: "src/main.js",
			name: "UniversWorkshop",
			formats: ["iife"],
			fileName: () => "workshop.js",
			cssFileName: "workshop",
		},
		cssCodeSplit: false,
	},
});
