import {defineConfig} from '../workshop-vue/node_modules/vite/dist/node/index.js';
import vue from '../workshop-vue/node_modules/@vitejs/plugin-vue/dist/index.mjs';
import {fileURLToPath} from 'node:url';
export default defineConfig({plugins:[vue()],resolve:{alias:{vue:fileURLToPath(new URL('../workshop-vue/node_modules/vue/dist/vue.runtime.esm-bundler.js',import.meta.url))}},define:{'process.env.NODE_ENV':'"production"'},build:{outDir:'../../mat_reco/public/js/glass_stock_dist',emptyOutDir:true,lib:{entry:'src/main.js',name:'UGGlassStock',formats:['iife'],fileName:()=> 'glass-stock-r2.js',cssFileName:'glass-stock'},cssCodeSplit:false}});
