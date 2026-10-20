import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
    plugins: [vue()],

    define: {
        "process.env.NODE_ENV": JSON.stringify("production")
    },

    build: {
        outDir: "../../mat_reco/public/js/mcp_vue_dist",
        emptyOutDir: true,

        lib: {
            entry: "src/main.js",
            name: "MatRecoMCPVue",
            formats: ["iife"],
            fileName: () => "mcp_vue.iife.js"
        },

        cssCodeSplit: false
    }
});