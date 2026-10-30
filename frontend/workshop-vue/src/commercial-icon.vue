<script setup>
import {computed} from 'vue';
const props=defineProps({name:{type:String,default:'document'}});
const paths={
 document:['M14 2H5a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9z','M14 2v7h7M7 13h10M7 17h7'],
 search:['m21 21-5-5','M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0Z'],
 refresh:['M20 7v5h-5M4 17v-5h5','M6 6a8 8 0 0 1 13 3M18 18a8 8 0 0 1-13-3'],
 print:['M6 9V3h12v6M6 17H3V9h18v8h-3M6 14h12v7H6z','M17 11h1'],
 truck:['M2 5h12v12H2zM14 9h4l4 5v3h-8','M8 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0ZM21 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z'],
 coins:['M3 5a7 3 0 1 0 14 0 7 3 0 1 0-14 0M3 5v5c0 1.7 3.1 3 7 3M3 10v5c0 1.7 3.1 3 7 3','M10 14a6 3 0 1 0 12 0 6 3 0 1 0-12 0M10 14v5c0 1.7 2.7 3 6 3s6-1.3 6-3v-5'],
 client:['M20 21v-2a6 6 0 0 0-6-6h-4a6 6 0 0 0-6 6v2','M16 5a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z'],
 project:['M3 3h18v18H3z','M3 15l5-5 4 4 3-3 6 5M8 7h.01'],
 gear:['M9 3h6l1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1z','M15.5 12a3.5 3.5 0 1 1-7 0 3.5 3.5 0 0 1 7 0Z'],
 external:['M15 3h6v6M21 3l-9 9','M10 3H3v18h18v-7'],
 close:['m5 5 14 14M5 19 19 5'],
 chevron:['m9 5 7 7-7 7'],
 plus:['M12 5v14M5 12h14'],
 minus:['M5 12h14'],
 fit:['M8 3H3v5M16 3h5v5M21 16v5h-5M8 21H3v-5'],
 card:['M3 5h18v14H3zM3 9h18M6 14h4'],
 lock:['M6 10h12v11H6z','M8 10V6a4 4 0 0 1 8 0v4'],
 check:['m5 12 4 4L19 6'],
 square:['M3 3h18v18H3z'],
 clock:['M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Z','M12 6v6l4 2'],
};
const segments=computed(()=>paths[props.name]||paths.document);
</script>
<template><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path v-for="(path,index) in segments" :key="index" :d="path"/></svg></template>
