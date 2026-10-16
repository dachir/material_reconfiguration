import { createApp } from "vue";
import App from "./App.vue";
import "./style.css";
import "./dialog-theme.js";
import "./dialog-theme.css";
export function mount(element) {
	const app = createApp(App);
	const component = app.mount(element);
	return {
		show: () => component.show(),
		hide: () => component.hide(),
		unmount: () => app.unmount(),
	};
}

import Chantiers from "./Chantiers.vue";
export function mountChantiers(element) {
 const app=createApp(Chantiers); const component=app.mount(element);
 return {show:()=>component.show(),hide:()=>component.hide(),unmount:()=>app.unmount()};
}

import TechnicalStudy from "./TechnicalStudy.vue";
export function mountTechnicalStudy(element){const app=createApp(TechnicalStudy);const component=app.mount(element);return {show:()=>component.show(),hide:()=>component.hide(),unmount:()=>app.unmount()};}
