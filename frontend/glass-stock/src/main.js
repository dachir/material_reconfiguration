import {createApp} from 'vue';
import App from './App.vue';
import './style.css';
export function mount(element){const app=createApp(App);const vm=app.mount(element);return {show:()=>vm.show(),hide:()=>vm.hide(),unmount:()=>app.unmount()};}
