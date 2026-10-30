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
export function mountTechnicalStudy(element,onStatusChange){const app=createApp(TechnicalStudy,{onStatusChange});const component=app.mount(element);return {show:()=>component.show(),hide:()=>component.hide(),unmount:()=>app.unmount()};}

import CommercialCockpit from "./CommercialCockpit.vue";
export function mountCommercialCockpit(element) {
	const app = createApp(CommercialCockpit);
	const component = app.mount(element);
	return {
		show: () => component.show(),
		hide: () => component.hide(),
		unmount: () => app.unmount(),
	};
}
